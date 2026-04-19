import socket
import serial
import time
import threading

# =======================
# CONFIGURABLE SETTINGS
# =======================
HOST = '0.0.0.0'  # Listen on all available interfaces
PORT = 5000       # Port for TCP connection
SERIAL_PORT = '/dev/ttyACM0' # Arduino serial port
BAUDRATE = 9600   # Arduino serial baudrate
RETRY_INTERVAL = 5 # Seconds to wait before retrying connection

# Global flag for graceful shutdown
shutdown_flag = threading.Event()

def setup_serial():
    """Sets up and returns a serial connection to Arduino."""
    ser = None
    while not shutdown_flag.is_set():
        try:
            print(f"Attempting to connect to Arduino on {SERIAL_PORT} at {BAUDRATE} baud...")
            ser = serial.Serial(SERIAL_PORT, BAUDRATE, timeout=1)
            print("Arduino connected.")
            return ser
        except serial.SerialException as e:
            print(f"Error connecting to Arduino: {e}. Retrying in {RETRY_INTERVAL} seconds...")
            time.sleep(RETRY_INTERVAL)
    return None

def handle_client(conn, addr, ser):
    """Handles communication with a connected laptop client."""
    print(f"Connected from: {addr}")
    buffer = ""
    try:
        while not shutdown_flag.is_set():
            data = conn.recv(1024)
            if not data:
                print(f"Client {addr} disconnected.")
                break
            
            buffer += data.decode('utf-8')
            
            while '\n' in buffer:
                line, buffer = buffer.split('\n', 1)
                message = line.strip()
                if message:
                    print(f"Received: {message}")
                    try:
                        # Forward data to Arduino
                        ser.write((message + '\n').encode('utf-8'))
                    except serial.SerialException as e:
                        print(f"Serial write error: {e}. Attempting to re-establish serial connection.")
                        ser.close()
                        ser = setup_serial() # Re-establish serial connection
                        if ser:
                            ser.write((message + '\n').encode('utf-8')) # Try writing again
                        else:
                            print("Failed to re-establish serial connection. Data lost.")

    except Exception as e:
        print(f"Error handling client {addr}: {e}")
    finally:
        conn.close()
        print(f"Connection with {addr} closed.")

def main():
    server_socket = None
    ser = None
    try:
        ser = setup_serial()
        if not ser:
            print("Could not establish serial connection. Exiting.")
            return

        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.settimeout(1) # Set a timeout for accept to check shutdown_flag

        print(f"Starting TCP server on {HOST}:{PORT}...")
        server_socket.bind((HOST, PORT))
        server_socket.listen(1)
        print("Waiting for laptop connection...")

        while not shutdown_flag.is_set():
            try:
                conn, addr = server_socket.accept()
                # Start a new thread to handle the client connection
                client_handler = threading.Thread(target=handle_client, args=(conn, addr, ser))
                client_handler.daemon = True # Allow main program to exit even if threads are running
                client_handler.start()
            except socket.timeout:
                continue # Timeout occurred, check shutdown_flag again
            except Exception as e:
                print(f"Error accepting connection: {e}")
                time.sleep(RETRY_INTERVAL)

    except KeyboardInterrupt:
        print("Shutdown initiated by user (Ctrl+C).")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
    finally:
        print("Server shutting down...")
        shutdown_flag.set() # Signal all threads to shut down
        if ser and ser.is_open:
            # Send stop command to Arduino before closing serial
            try:
                ser.write(b"0,0,0,0,0,0,0,0\n")
                print("Sent stop command to Arduino.")
            except serial.SerialException as e:
                print(f"Error sending stop command to Arduino: {e}")
            ser.close()
            print("Arduino serial connection closed.")
        if server_socket:
            server_socket.close()
            print("TCP server socket closed.")

if __name__ == "__main__":
    main()
