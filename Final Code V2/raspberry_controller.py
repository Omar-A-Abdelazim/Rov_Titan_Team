import socket
import serial
import time
import threading
import binascii
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(asctime)s - %(message)s")

# =======================
# CONFIGURABLE SETTINGS
# =======================
HOST = '0.0.0.0'  # Listen on all available interfaces
PORT = 5000       # Port for TCP connection
SERIAL_PORT = '/dev/ttyACM0' # Arduino serial port
BAUDRATE = 9600   # Arduino serial baudrate
RETRY_INTERVAL = 5 # Seconds to wait before retrying connection

# Define a buffer size for TCP communication on Raspberry Pi side
TCP_BUFFER_SIZE = 2048 # Max size for incoming TCP data before clearing

# =======================
# COMMUNICATION PROTOCOL DEFINITIONS
# =======================
START_DELIMITER = b'<'
END_DELIMITER = b'>'
PACKET_TYPE_MOTOR = b'M'
PACKET_TYPE_SENSOR = b'S'

# Global flag for graceful shutdown
shutdown_flag = threading.Event()

# Global variable to hold the serial connection
ser = None
serial_lock = threading.Lock()

# List to hold client connections for sending sensor data
connected_clients = []
client_lock = threading.Lock()

def calculate_checksum(data_bytes):
    checksum = 0
    for byte_val in data_bytes:
        checksum ^= byte_val
    return checksum

def setup_serial():
    """Sets up and returns a serial connection to Arduino."""
    global ser
    with serial_lock:
        if ser and ser.is_open:
            logging.info("Closing existing serial connection.")
            ser.close()
        ser = None # Clear stale reference

        while not shutdown_flag.is_set():
            try:
                logging.info(f"Attempting to connect to Arduino on {SERIAL_PORT} at {BAUDRATE} baud...")
                new_ser = serial.Serial(SERIAL_PORT, BAUDRATE, timeout=1)
                ser = new_ser
                logging.info("Arduino connected.")
                return ser
            except serial.SerialException as e:
                logging.error(f"Error connecting to Arduino: {e}. Retrying in {RETRY_INTERVAL} seconds...")
                time.sleep(RETRY_INTERVAL)
            except Exception as e:
                logging.error(f"Unexpected error during serial setup: {e}. Retrying in {RETRY_INTERVAL} seconds...")
                time.sleep(RETRY_INTERVAL)
    return None

def parse_packet(raw_packet):
    """Parses a raw packet string and validates checksum.
    Returns (packet_type, data_payload) or None if invalid.
    """
    try:
        if not raw_packet.startswith(START_DELIMITER) or not raw_packet.endswith(END_DELIMITER):
            logging.warning(f"Malformed packet (delimiters missing): {raw_packet}")
            return None

        # Remove delimiters
        content = raw_packet[len(START_DELIMITER):-len(END_DELIMITER)]
        
        parts = content.split(b'|')
        if len(parts) != 3: # Expecting TYPE | DATA | CHECKSUM
            logging.warning(f"Malformed packet structure (wrong number of parts): {raw_packet}")
            return None

        packet_type = parts[0]
        data_section = parts[1]
        received_checksum_hex = parts[2]

        # Calculate checksum of type + data (this is the agreed-upon method)
        data_to_checksum = packet_type + b'|' + data_section
        calculated_checksum = calculate_checksum(data_to_checksum)
        
        # Convert received checksum from hex string to byte
        try:
            received_checksum = int(received_checksum_hex, 16)
        except ValueError:
            logging.warning(f"Invalid checksum hex string: {received_checksum_hex.decode()}. Packet: {raw_packet}")
            return None

        if calculated_checksum == received_checksum:
            return packet_type, data_section.decode('utf-8')
        else:
            logging.warning(f"Checksum mismatch! Received: {received_checksum_hex.decode()}, Calculated: {calculated_checksum:X}. Packet: {raw_packet}")
            return None
    except Exception as e:
        logging.error(f"Error parsing packet: {e}. Packet: {raw_packet}")
        return None

def read_from_arduino():
    """Continuously reads data from Arduino, parses it, and forwards to connected clients."""
    global ser
    buffer = b''
    while not shutdown_flag.is_set():
        if not ser or not ser.is_open:
            logging.debug("Serial not open, attempting to re-establish...")
            setup_serial() # Attempt to re-establish serial connection
            time.sleep(0.5) # Give some time for connection
            continue

        try:
            # Read byte by byte to handle partial packets more robustly
            if ser.in_waiting > 0:
                byte = ser.read(1)
                buffer += byte

                # Check for END_DELIMITER to signify a potential complete packet
                if byte == END_DELIMITER:
                    # Find the last START_DELIMITER to extract the most recent packet
                    start_idx = buffer.rfind(START_DELIMITER)
                    if start_idx != -1:
                        potential_packet = buffer[start_idx:]
                        packet_result = parse_packet(potential_packet)
                        
                        if packet_result:
                            packet_type, data_payload = packet_result
                            if packet_type == PACKET_TYPE_SENSOR:
                                # Reconstruct the valid packet to forward (including delimiters and checksum)
                                # The parse_packet already validated the checksum, so we can forward the raw_packet
                                full_packet_to_forward = potential_packet # Already bytes
                                # logging.debug(f"Forwarding sensor: {full_packet_to_forward}")
                                with client_lock:
                                    # Iterate over a copy to safely remove disconnected clients
                                    for client_conn in list(connected_clients):
                                        try:
                                            client_conn.sendall(full_packet_to_forward + b'\n')
                                        except socket.error as e:
                                            logging.warning(f"Error sending sensor data to client: {e}. Removing client.")
                                            with client_lock:
                                                if client_conn in connected_clients:
                                                    connected_clients.remove(client_conn)
                                            client_conn.close()
                            else:
                                logging.warning(f"Received non-sensor packet from Arduino: {packet_type}. Discarding.")
                        
                        # Clear the processed packet from the buffer
                        buffer = buffer[start_idx + len(potential_packet):] # Corrected buffer clearing
                    else:
                        # No start delimiter found for the current end delimiter, clear up to end delimiter
                        logging.debug("No START_DELIMITER found for END_DELIMITER. Clearing buffer up to END_DELIMITER.")
                        buffer = buffer[buffer.rfind(END_DELIMITER) + len(END_DELIMITER):]

            # Prevent buffer from growing indefinitely if no end delimiter is found
            if len(buffer) > TCP_BUFFER_SIZE * 2: # Use TCP_BUFFER_SIZE for consistency
                logging.warning("Serial buffer overflow, clearing...")
                buffer = b'' # Clear buffer to prevent memory issues

        except serial.SerialException as e:
            logging.error(f"Serial read error: {e}. Attempting to re-establish serial connection.")
            setup_serial() # Re-establish serial connection
            buffer = b'' # Clear buffer on serial error
        except Exception as e:
            logging.error(f"Error reading from Arduino: {e}")
            buffer = b'' # Clear buffer on other errors
        time.sleep(0.005) # Small delay to prevent busy-waiting

def handle_client(conn, addr):
    """Handles communication with a connected laptop client."""
    global ser
    logging.info(f"Connected from: {addr}")
    buffer = b''

    with client_lock:
        connected_clients.append(conn)

    try:
        while not shutdown_flag.is_set():
            data = conn.recv(1024)
            if not data:
                logging.info(f"Client {addr} disconnected.")
                break
            
            buffer += data
            
            # Process all complete packets in the buffer
            while True:
                start_idx = buffer.find(START_DELIMITER)
                end_idx = buffer.find(END_DELIMITER, start_idx if start_idx != -1 else 0)

                if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                    raw_packet = buffer[start_idx : end_idx + len(END_DELIMITER)]
                    packet_result = parse_packet(raw_packet)

                    if packet_result:
                        packet_type, data_payload = packet_result
                        if packet_type == PACKET_TYPE_MOTOR:
                            # logging.debug(f"Received motor command from Laptop: {data_payload}")
                            if ser and ser.is_open:
                                with serial_lock:
                                    try:
                                        # Forward data to Arduino (motor commands)
                                        ser.write(raw_packet + b'\n') # Add newline for Arduino Serial.readStringUntil
                                    except serial.SerialException as e:
                                        logging.error(f"Serial write error: {e}. Attempting to re-establish serial connection.")
                                        # Attempt to re-establish serial connection, but don't block client handler
                                        threading.Thread(target=setup_serial).start()
                                        # If serial is not immediately available, data is lost for this packet
                                    except Exception as e:
                                        logging.error(f"Unexpected error during serial write: {e}")
                            else:
                                logging.warning("Serial connection not available. Data not sent to Arduino.")
                        else:
                            logging.warning(f"Received non-motor packet from Laptop: {packet_type}. Discarding.")
                    
                    # Remove the processed packet from the buffer
                    buffer = buffer[end_idx + len(END_DELIMITER):]
                else:
                    break # No complete packet found

            # Prevent buffer from growing indefinitely if no end delimiter is found
            if len(buffer) > TCP_BUFFER_SIZE:
                logging.warning("TCP buffer overflow, clearing...")
                buffer = b''

    except Exception as e:
        logging.error(f"Error handling client {addr}: {e}")
    finally:
        with client_lock:
            if conn in connected_clients:
                connected_clients.remove(conn)
        conn.close()
        logging.info(f"Connection with {addr} closed.")

def main():
    global ser
    server_socket = None
    try:
        ser = setup_serial()
        if not ser:
            logging.critical("Could not establish serial connection. Exiting.")
            return

        # Start thread to read from Arduino
        arduino_read_thread = threading.Thread(target=read_from_arduino)
        arduino_read_thread.daemon = True
        arduino_read_thread.start()

        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.settimeout(1) # Set a timeout for accept to check shutdown_flag

        logging.info(f"Starting TCP server on {HOST}:{PORT}...")
        server_socket.bind((HOST, PORT))
        server_socket.listen(5) # Allow multiple client connections
        logging.info("Waiting for laptop connection...")

        while not shutdown_flag.is_set():
            try:
                conn, addr = server_socket.accept()
                # Start a new thread to handle the client connection
                client_handler = threading.Thread(target=handle_client, args=(conn, addr))
                client_handler.daemon = True # Allow main program to exit even if threads are running
                client_handler.start()
            except socket.timeout:
                continue # Timeout occurred, check shutdown_flag again
            except Exception as e:
                logging.error(f"Error accepting connection: {e}")
                time.sleep(RETRY_INTERVAL)

    except KeyboardInterrupt:
        logging.info("Shutdown initiated by user (Ctrl+C).")
    except Exception as e:
        logging.critical(f"An unexpected error occurred in main: {e}")
    finally:
        logging.info("Server shutting down...")
        shutdown_flag.set()
        # Wait for arduino_read_thread to finish if it's still running
        if arduino_read_thread.is_alive():
            arduino_read_thread.join(timeout=2) # Give it a chance to clean up

        if ser and ser.is_open:
            with serial_lock:
                try:
                    # Construct a stop command packet to send to Arduino
                    stop_data_payload = b'0,0,0,0,0,0,0,0,0,0'
                    stop_packet_type = PACKET_TYPE_MOTOR
                    data_to_checksum = stop_packet_type + b'|' + stop_data_payload
                    checksum = calculate_checksum(data_to_checksum)
                    stop_packet = START_DELIMITER + stop_packet_type + b'|' + stop_data_payload + b'|' + hex(checksum)[2:].encode() + END_DELIMITER + b'\n'
                    ser.write(stop_packet)
                    logging.info("Sent stop command to Arduino.")
                except serial.SerialException as e:
                    logging.error(f"Error sending stop command to Arduino during shutdown: {e}")
                except Exception as e:
                    logging.error(f"Unexpected error sending stop command to Arduino during shutdown: {e}")
                ser.close()
                logging.info("Arduino serial connection closed.")
        if server_socket:
            server_socket.close()
            logging.info("TCP server socket closed.")

if __name__ == "__main__":
    main()
