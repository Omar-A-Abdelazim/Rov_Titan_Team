import cv2
import torch
import numpy as np
import time
import threading
from pathlib import Path
from ultralytics import YOLO
import pdfplumber
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.backends.backend_pdf as pdf_backend
import re
import queue
import tkinter as tk
from tkinter import scrolledtext, filedialog, ttk
import math
import sys
import warnings

warnings.filterwarnings("ignore", category=FutureWarning)

sys.path.insert(0, r"C:\Users\aalli\python coding\front_code")

try:
    from mirnet_model import MIRNet
    MIRNET_AVAILABLE = True
    print("MIRNet model loaded successfully")
except Exception as e:
    print(f"Could not import MIRNet: {e}")
    MIRNET_AVAILABLE = False


def distance_to_nautical_miles(latitude_diff):
    return abs(latitude_diff) * 60


def surface_threat_level(distance):
    if distance < 5:
        return "RED"
    elif distance <= 10:
        return "YELLOW"
    else:
        return "GREEN"


def subsea_threat_level(keel_depth, water_depth):
    percentage = (keel_depth / water_depth) * 100
    if percentage >= 110:
        return "GREEN", percentage
    elif 90 <= percentage < 110:
        return "RED", percentage
    elif 70 <= percentage < 90:
        return "YELLOW", percentage
    else:
        return "GREEN", percentage


def extract_iceberg_from_pdf(pdf_path):
    iceberg_data = None
    platforms = []
    all_text = ""
    
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                all_text += text + "\n"
    
    lat_match = re.search(r'Latitude\s*([NS]?)\s*(\d+\.?\d*)\s*°?\s*([NS]?)', all_text, re.IGNORECASE)
    lon_match = re.search(r'Longitude\s*([EW]?)\s*(\d+\.?\d*)\s*°?\s*([EW]?)', all_text, re.IGNORECASE)
    heading_match = re.search(r'Heading\s*(\d+\.?\d*)\s*°?', all_text, re.IGNORECASE)
    keel_match = re.search(r'Keel\s*Depth\s*(\d+\.?\d*)\s*m', all_text, re.IGNORECASE)
    
    if lat_match and lon_match and heading_match and keel_match:
        lat = float(lat_match.group(2))
        if 'S' in lat_match.group(1) or 'S' in lat_match.group(3):
            lat = -lat
        
        lon = float(lon_match.group(2))
        if 'W' in lon_match.group(1) or 'W' in lon_match.group(3):
            lon = -lon
        
        iceberg_data = {
            "Latitude": lat,
            "Longitude": lon,
            "Heading": float(heading_match.group(1)),
            "Keel Depth": float(keel_match.group(1))
        }
    
    known_platform_names = ['Hibernia', 'Sea Rose', 'Terra Nova', 'Hebron', 'Alpha', 'Bravo', 'Charlie', 'Delta']
    
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            for table in tables:
                if not table or len(table) < 2:
                    continue
                
                headers = [str(cell).lower() if cell else "" for cell in table[0]]
                
                name_col = None
                lat_col = None
                lon_col = None
                depth_col = None
                
                for idx, cell in enumerate(headers):
                    if 'platform' in cell or 'name' in cell or 'location' in cell:
                        name_col = idx
                    if 'lat' in cell:
                        lat_col = idx
                    if 'lon' in cell or 'long' in cell:
                        lon_col = idx
                    if 'depth' in cell or 'water' in cell:
                        depth_col = idx
                
                if name_col is not None and lat_col is not None and depth_col is not None:
                    for row in table[1:]:
                        if len(row) > max(name_col, lat_col, lon_col if lon_col else depth_col, depth_col):
                            try:
                                name = str(row[name_col]).strip() if row[name_col] else ""
                                if not name or name.lower() in ['', 'platform', 'name', 'location']:
                                    continue
                                
                                lat = float(re.findall(r'-?\d+\.?\d*', str(row[lat_col]))[0])
                                if lon_col is not None:
                                    lon = float(re.findall(r'-?\d+\.?\d*', str(row[lon_col]))[0])
                                else:
                                    lon = lat
                                
                                depth = float(re.findall(r'-?\d+\.?\d*', str(row[depth_col]))[0])
                                
                                lat = abs(lat)
                                lon = -abs(lon)
                                
                                platforms.append({
                                    "Name": name,
                                    "Latitude": lat,
                                    "Longitude": lon,
                                    "Water Depth": depth
                                })
                            except:
                                continue
                
                else:
                    for row in table[1:]:
                        row_text = ' '.join([str(cell) for cell in row if cell])
                        for known_name in known_platform_names:
                            if known_name in row_text:
                                numbers = re.findall(r'-?\d+\.?\d*', row_text)
                                if len(numbers) >= 3:
                                    platforms.append({
                                        "Name": known_name,
                                        "Latitude": abs(float(numbers[0])),
                                        "Longitude": -abs(float(numbers[1])),
                                        "Water Depth": float(numbers[2])
                                    })
                                break
    
    if not platforms:
        for line in all_text.split('\n'):
            numbers = re.findall(r'-?\d+\.?\d*', line)
            if len(numbers) >= 3:
                possible_name = re.sub(r'[^a-zA-Z\s]', '', line).strip()
                if possible_name and len(possible_name) > 2:
                    platforms.append({
                        "Name": possible_name[:20],
                        "Latitude": abs(float(numbers[0])),
                        "Longitude": -abs(float(numbers[1])),
                        "Water Depth": float(numbers[2])
                    })
    
    return iceberg_data, platforms


class ConfirmationDialog:
    def __init__(self):
        self.root = None
        self.result_queue = queue.Queue()
        
    def show(self, title, message, show_buttons=True):
        self.root = tk.Tk()
        self.root.title(title)
        self.root.geometry("600x400")
        self.root.protocol("WM_DELETE_WINDOW", self._on_cancel)
        
        text_area = scrolledtext.ScrolledText(self.root, wrap=tk.WORD, font=("Courier", 10))
        text_area.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        text_area.insert(tk.END, message)
        text_area.config(state=tk.DISABLED)
        
        if show_buttons:
            button_frame = tk.Frame(self.root)
            button_frame.pack(pady=10)
            tk.Button(button_frame, text="Correct", command=self._on_yes, width=15, bg='#90EE90').pack(side=tk.LEFT, padx=10)
            tk.Button(button_frame, text="Incorrect", command=self._on_no, width=15, bg='#FFB6C1').pack(side=tk.LEFT, padx=10)
        
        self.root.mainloop()
        return self.result_queue.get()
        
    def _on_yes(self):
        self.result_queue.put('yes')
        self.root.quit()
        self.root.destroy()
        
    def _on_no(self):
        self.result_queue.put('no')
        self.root.quit()
        self.root.destroy()
        
    def _on_cancel(self):
        self.result_queue.put('cancel')
        self.root.quit()
        self.root.destroy()


def pick_pdf_file():
    root = tk.Tk()
    root.withdraw()
    file_path = filedialog.askopenfilename(title="Select PDF file", filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")])
    root.destroy()
    return file_path


def apply_perspective_transform(image, corner_points):
    h, w = image.shape[:2]
    src = np.float32(corner_points)
    dst = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    matrix = cv2.getPerspectiveTransform(src, dst)
    transformed = cv2.warpPerspective(image, matrix, (w, h))
    return transformed


class SettingsPanel:
    def __init__(self):
        self.root = None
        self.confidence = 0.5
        self.image_size = 1600
        self.enhance_res = "640x480"
        self.is_running = True
        self.on_update = None
        
    def set_callback(self, callback):
        self.on_update = callback
        
    def show(self):
        self.root = tk.Tk()
        self.root.title("Control Panel")
        self.root.geometry("400x350")
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        
        tk.Label(self.root, text="Object Detection Settings", font=("Arial", 12, "bold")).pack(pady=5)
        
        conf_frame = tk.Frame(self.root)
        conf_frame.pack(pady=5)
        tk.Label(conf_frame, text="Confidence (0.0-1.0):").pack(side=tk.LEFT)
        self.conf_entry = tk.Entry(conf_frame, width=10)
        self.conf_entry.insert(0, str(self.confidence))
        self.conf_entry.pack(side=tk.LEFT, padx=5)
        tk.Button(conf_frame, text="Set", command=self._update_confidence).pack(side=tk.LEFT)
        
        size_frame = tk.Frame(self.root)
        size_frame.pack(pady=5)
        tk.Label(size_frame, text="Image Size (500-2000):").pack(side=tk.LEFT)
        self.size_entry = tk.Entry(size_frame, width=10)
        self.size_entry.insert(0, str(self.image_size))
        self.size_entry.pack(side=tk.LEFT, padx=5)
        tk.Button(size_frame, text="Set", command=self._update_image_size).pack(side=tk.LEFT)
        
        tk.Label(self.root, text="Underwater Enhancement Resolution", font=("Arial", 12, "bold")).pack(pady=10)
        
        resolutions = ["320x240", "480x360", "640x480", "800x600", "960x720", "1280x960", "1600x1200", "1920x1440"]
        self.res_var = tk.StringVar(value=self.enhance_res)
        res_menu = ttk.Combobox(self.root, textvariable=self.res_var, values=resolutions, state="readonly")
        res_menu.pack(pady=5)
        tk.Button(self.root, text="Set Resolution", command=self._update_resolution).pack(pady=5)
        
        tk.Label(self.root, text="Current Settings:", font=("Arial", 10, "bold")).pack(pady=10)
        self.status_label = tk.Label(self.root, text=f"Confidence: {self.confidence}\nImage Size: {self.image_size}\nEnhance Res: {self.enhance_res}", justify=tk.LEFT)
        self.status_label.pack()
        
        self.root.mainloop()
        
    def _update_confidence(self):
        try:
            val = float(self.conf_entry.get())
            if 0 <= val <= 1:
                self.confidence = round(val, 2)
                if self.on_update:
                    self.on_update('confidence', self.confidence)
                self._update_status()
            else:
                print("Confidence must be between 0 and 1")
        except:
            print("Invalid confidence value")
            
    def _update_image_size(self):
        try:
            val = int(self.size_entry.get())
            if 500 <= val <= 2000:
                self.image_size = val
                if self.on_update:
                    self.on_update('imgsz', self.image_size)
                self._update_status()
            else:
                print("Image size must be between 500 and 2000")
        except:
            print("Invalid image size")
            
    def _update_resolution(self):
        self.enhance_res = self.res_var.get()
        if self.on_update:
            self.on_update('resolution', self.enhance_res)
        self._update_status()
        
    def _update_status(self):
        self.status_label.config(text=f"Confidence: {self.confidence}\nImage Size: {self.image_size}\nEnhance Res: {self.enhance_res}")
        
    def _close(self):
        self.is_running = False
        if self.root:
            self.root.quit()
            self.root.destroy()


class PerspectiveEditor:
    def __init__(self, image):
        self.original = image.copy()
        self.h, self.w = image.shape[:2]
        self.corners = [[0, 0], [self.w, 0], [self.w, self.h], [0, self.h]]
        self.dragging = False
        self.drag_index = -1
        self.window_name = "Perspective Transform - Drag corners | S:Save | ESC:Cancel"
        self.is_running = True
        self.result = None
        
        cv2.namedWindow(self.window_name)
        cv2.setMouseCallback(self.window_name, self._on_mouse)
        self._update_preview()
        
    def _on_mouse(self, event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            for i, pt in enumerate(self.corners):
                if abs(x - pt[0]) < 15 and abs(y - pt[1]) < 15:
                    self.dragging = True
                    self.drag_index = i
                    break
        elif event == cv2.EVENT_MOUSEMOVE:
            if self.dragging and self.drag_index >= 0:
                x = max(0, min(self.w, x))
                y = max(0, min(self.h, y))
                self.corners[self.drag_index] = [x, y]
                self._update_preview()
        elif event == cv2.EVENT_LBUTTONUP:
            self.dragging = False
            self.drag_index = -1
            
    def _update_preview(self):
        preview = self.original.copy()
        warped = apply_perspective_transform(self.original, self.corners)
        preview = cv2.addWeighted(preview, 0.5, warped, 0.5, 0)
        for i, pt in enumerate(self.corners):
            cv2.circle(preview, (int(pt[0]), int(pt[1])), 8, (0, 255, 0), -1)
            cv2.putText(preview, str(i), (int(pt[0])+5, int(pt[1])-5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
        cv2.imshow(self.window_name, preview)
        
    def run(self):
        while self.is_running:
            key = cv2.waitKey(10) & 0xFF
            if key == ord('s'):
                self.result = apply_perspective_transform(self.original, self.corners)
                self.is_running = False
            elif key == 27:
                self.is_running = False
                self.result = None
        cv2.destroyWindow(self.window_name)
        return self.result


class UnderwaterEnhancer:
    def __init__(self):
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        self.input_width = 640
        self.input_height = 480
        if MIRNET_AVAILABLE:
            model_path = r'C:/Users/aalli/Documents/underwater_mirnet/backups/2.0/continued/best_fit.pth'
            try:
                checkpoint = torch.load(model_path, map_location=self.device)
                self.model = MIRNet(num_rrg=2, num_mrb=1, channels=16).to(self.device).eval()
                self.model.load_state_dict(checkpoint['model_state_dict'])
                self.is_ready = True
                print("MIRNet model loaded")
            except Exception as e:
                print(f"Failed to load MIRNet model: {e}")
                self.is_ready = False
        else:
            self.is_ready = False
    
    def set_resolution(self, resolution):
        try:
            w, h = map(int, resolution.split('x'))
            self.input_width = w
            self.input_height = h
            print(f"Enhancement resolution set to {w}x{h}")
        except:
            pass
        
    def enhance(self, image):
        if self.is_ready:
            small = cv2.resize(image, (self.input_width, self.input_height))
            rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
            tensor = torch.from_numpy(rgb).permute(2,0,1).float().unsqueeze(0).to(self.device) / 255.0
            with torch.no_grad():
                enhanced = self.model(tensor)
            output = enhanced[0].cpu().permute(1,2,0).numpy()
            output_bgr = cv2.cvtColor((output * 255).astype(np.uint8), cv2.COLOR_RGB2BGR)
            output_full = cv2.resize(output_bgr, (image.shape[1], image.shape[0]))
            return output_full
        else:
            return image


class CrabDetector:
    def __init__(self):
        model_path = Path(r"C:\Users\aalli\Documents\crab_training_final7\phase_01\weights\best.pt")
        self.confidence = 0.5
        self.image_size = 1600
        self.class_colors = {0: (0, 255, 0), 1: (0, 0, 255)}
        self.class_names = {0: "green_crab", 1: "other_crab"}
        self.last_green_count = -1
        try:
            self.model = YOLO(str(model_path))
            self.is_ready = True
            print("YOLO model loaded")
        except Exception as e:
            print(f"Failed to load YOLO model: {e}")
            self.is_ready = False
    
    def set_confidence(self, conf):
        self.confidence = conf
        
    def set_image_size(self, size):
        self.image_size = size
        
    def detect(self, image):
        if not self.is_ready:
            return image, 0, 0
        results = self.model(image, conf=self.confidence, imgsz=self.image_size, verbose=False)[0]
        output = image.copy()
        green_count = 0
        other_count = 0
        for box in results.boxes:
            class_id = int(box.cls.item())
            confidence = float(box.conf.item())
            x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
            color = self.class_colors.get(class_id, (255, 255, 255))
            label = f"{self.class_names.get(class_id, class_id)} {confidence:.2f}"
            cv2.rectangle(output, (x1, y1), (x2, y2), color, 2)
            cv2.putText(output, label, (x1, max(y1 - 8, 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
            if class_id == 0:
                green_count += 1
            else:
                other_count += 1
        
        if green_count != self.last_green_count:
            self.last_green_count = green_count
            print(f"Green crabs detected: {green_count}")
        
        return output, green_count, other_count


class FrameCollector:
    def __init__(self):
        self.is_capturing = False
        self.previous_frame = None
        self.frame_count = 0
        self.save_folder = Path(r"C:\Users\aalli\Documents\rapid_3d_frames")
        self.save_folder.mkdir(parents=True, exist_ok=True)
        self.diff_threshold = 15
        self.blur_threshold = 65
        self.max_frames = 200
        
    def start(self):
        self.is_capturing = True
        self.previous_frame = None
        self.frame_count = 0
        print("3D reconstruction capture started (sharp + different frames only)")
        
    def stop(self):
        self.is_capturing = False
        if self.frame_count > 0:
            print(f"Captured {self.frame_count} frames for 3D model. Saved to {self.save_folder}")
        
    def process(self, frame):
        if not self.is_capturing:
            return
        if self.frame_count >= self.max_frames:
            self.is_capturing = False
            print(f"Reached {self.max_frames} frames")
            return
        
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        blur_score = cv2.Laplacian(gray, cv2.CV_64F).var()
        if blur_score < self.blur_threshold:
            return
        
        if self.previous_frame is not None:
            difference = cv2.absdiff(gray, self.previous_frame).mean()
            if difference < self.diff_threshold:
                return
        
        output_path = self.save_folder / f"frame_{self.frame_count:04d}.jpg"
        cv2.imwrite(str(output_path), frame, [cv2.IMWRITE_JPEG_QUALITY, 100])
        self.previous_frame = gray
        self.frame_count += 1
        print(f"3D frame {self.frame_count}/{self.max_frames}", end='\r')


def analyze_frequency():
    pdf_path = pick_pdf_file()
    if not pdf_path:
        print("No file selected.")
        return
    
    if Path(pdf_path).exists():
        with pdfplumber.open(pdf_path) as pdf:
            first_page = pdf.pages[0]
            table = first_page.extract_table()
        
        if table and len(table) > 1:
            df = pd.DataFrame(table[1:], columns=table[0])
            counts = df.iloc[:, 1]
            counts_numeric = pd.to_numeric(counts, errors='coerce')
            total = counts_numeric.sum()
            
            if total > 0:
                df['Frequency'] = counts_numeric / total
                df['Frequency %'] = (counts_numeric / total * 100).round(2)
            else:
                df['Frequency'] = 0
                df['Frequency %'] = 0
            
            display_text = "EXTRACTED DATA:\n\n"
            display_text += df.to_string(index=False)
            
            dialog = ConfirmationDialog()
            result = dialog.show("Verify Frequency Data", display_text)
            
            if result == 'yes':
                output_path = Path(pdf_path).parent / f"{Path(pdf_path).stem}_with_frequency.pdf"
                fig, ax = plt.subplots(figsize=(14, 6))
                ax.axis('tight')
                ax.axis('off')
                ax.table(cellText=df.values, colLabels=df.columns, cellLoc='center', loc='center')
                plt.savefig(output_path, bbox_inches='tight', pad_inches=0.5)
                plt.close()
                print(f"Frequency analysis saved to {output_path}")
                return
    
    print("No valid table found or user rejected the data.")
    use_manual = input("Would you like to enter data manually? (yes/no): ").strip().lower()
    
    if use_manual == 'yes' or use_manual == 'y':
        species_data = []
        while True:
            name = input("Species name (or Enter to finish): ").strip()
            if not name:
                break
            count = int(input(f"  Number seen for {name}: "))
            species_data.append({"Species": name, "Number Seen": count})
        
        df = pd.DataFrame(species_data)
        total = df['Number Seen'].sum()
        
        if total > 0:
            df['Frequency'] = df['Number Seen'] / total
            df['Frequency %'] = (df['Number Seen'] / total * 100).round(2)
        else:
            df['Frequency'] = 0
            df['Frequency %'] = 0
        
        output_path = Path(r"C:\Users\aalli\Documents\frequency_manual_output.pdf")
        fig, ax = plt.subplots(figsize=(14, 6))
        ax.axis('tight')
        ax.axis('off')
        ax.table(cellText=df.values, colLabels=df.columns, cellLoc='center', loc='center')
        plt.savefig(output_path, bbox_inches='tight', pad_inches=0.5)
        plt.close()
        print(f"Manual frequency analysis saved to {output_path}")


def assess_threat():
    pdf_path = pick_pdf_file()
    if not pdf_path:
        print("No file selected.")
        return
    
    iceberg_data = None
    platforms = []
    
    if Path(pdf_path).exists():
        iceberg_data, platforms = extract_iceberg_from_pdf(pdf_path)
        
        if iceberg_data:
            display_text = "ICEBERG DATA:\n\n"
            display_text += f"Latitude: {abs(iceberg_data['Latitude'])}°{'N' if iceberg_data['Latitude'] >= 0 else 'S'}\n"
            display_text += f"Longitude: {abs(iceberg_data['Longitude'])}°{'W' if iceberg_data['Longitude'] <= 0 else 'E'}\n"
            display_text += f"Heading: {iceberg_data['Heading']}°\n"
            display_text += f"Keel Depth: {iceberg_data['Keel Depth']} m\n\n"
            display_text += "PLATFORM DATA:\n\n"
            for p in platforms:
                display_text += f"{p['Name']}: {abs(p['Latitude'])}°{'N' if p['Latitude'] >= 0 else 'S'}, {abs(p['Longitude'])}°{'W' if p['Longitude'] <= 0 else 'E'}, {p['Water Depth']}m\n"
            
            dialog = ConfirmationDialog()
            result = dialog.show("Verify Threat Data", display_text)
            
            if result == 'no' or result == 'cancel':
                print("Data rejected. Entering manual input.")
                iceberg_data = None
                platforms = []
        
        if not iceberg_data:
            print("\nEnter Iceberg Information")
            iceberg_data = {
                "Latitude": float(input("Latitude: ")),
                "Longitude": float(input("Longitude: ")),
                "Heading": float(input("Heading: ")),
                "Keel Depth": float(input("Keel depth: "))
            }
        
        if not platforms:
            print("\nEnter Platform Information")
            platforms = []
            while True:
                name = input("Platform name (Enter to finish): ").strip()
                if not name:
                    break
                lat = float(input(f"  {name} latitude: "))
                lon = float(input(f"  {name} longitude: "))
                depth = float(input(f"  {name} water depth: "))
                platforms.append({
                    "Name": name,
                    "Latitude": lat,
                    "Longitude": lon,
                    "Water Depth": depth
                })
    
    if not platforms:
        print("No platforms entered. Exiting.")
        return
    
    ice_lat = iceberg_data["Latitude"]
    ice_lon = iceberg_data["Longitude"]
    heading = iceberg_data["Heading"]
    keel = iceberg_data["Keel Depth"]
    
    results = []
    for platform in platforms:
        distance = abs(ice_lat - platform["Latitude"]) * 60
        surface = surface_threat_level(distance)
        subsea, ratio = subsea_threat_level(keel, platform["Water Depth"])
        results.append({
            "Platform": platform["Name"],
            "Distance (nm)": round(distance, 2),
            "Surface Threat": surface,
            "Keel/Water %": round(ratio, 1),
            "Subsea Threat": subsea
        })
    
    output_dir = Path(r"C:\Users\aalli\Documents\threat_assessment_output")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_pdf = output_dir / "threat_assessment_competition.pdf"
    
    fig, axes = plt.subplots(4, 1, figsize=(13, 11), gridspec_kw={'height_ratios': [1.2, 1.2, 0.6, 2.2]})
    
    axes[0].axis('off')
    axes[0].set_title("ICEBERG THREAT ASSESSMENT\nCompetition Rules", fontsize=15, fontweight='bold')
    axes[0].text(0.5, 0.4, "Distance = |iceberg_lat - platform_lat| × 60\n(1 minute of latitude = 1 nautical mile)", transform=axes[0].transAxes, fontsize=9, ha='center', va='center')
    
    platform_text = "PLATFORM LOCATIONS\n" + "-"*30 + "\n"
    for p in platforms:
        platform_text += f"{p['Name']}: {abs(p['Latitude'])}°{'N' if p['Latitude'] >= 0 else 'S'}, {abs(p['Longitude'])}°{'W' if p['Longitude'] <= 0 else 'E'}, {p['Water Depth']}m\n"
    axes[1].axis('off')
    axes[1].text(0.5, 0.5, platform_text, transform=axes[1].transAxes, fontsize=10, ha='center', va='center', family='monospace')
    
    axes[2].axis('off')
    info = f"Iceberg Position: {abs(ice_lat)}°{'N' if ice_lat>=0 else 'S'}, {abs(ice_lon)}°{'W' if ice_lon<=0 else 'E'}     Heading: {heading}°     Keel Depth: {keel} m"
    axes[2].text(0.5, 0.5, info, transform=axes[2].transAxes, fontsize=11, ha='center', va='center', bbox=dict(boxstyle='round', facecolor='#e8f4f8', alpha=0.8))
    
    axes[3].axis('off')
    df = pd.DataFrame(results)
    col_labels = df.columns.tolist()
    cell_text = df.values.tolist()
    
    tbl = axes[3].table(cellText=cell_text, colLabels=col_labels, cellLoc='center', loc='center')
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(10)
    tbl.scale(1.2, 2.0)
    
    for (i, j), cell in tbl.get_celld().items():
        if i == 0:
            cell.set_facecolor('#1a1a2e')
            cell.set_text_props(weight='bold', color='white')
        elif j in [2, 4]:
            threat = cell_text[i-1][j]
            colors = {"RED": '#FFCCCC', "YELLOW": '#FFFFCC', "GREEN": '#CCFFCC'}
            cell.set_facecolor(colors.get(threat, 'white'))
        else:
            cell.set_facecolor('#f9f9f9' if i % 2 == 0 else 'white')
    
    axes[3].set_title("THREAT ASSESSMENT RESULTS", fontsize=12, fontweight='bold')
    fig.tight_layout(pad=2.0)
    
    with pdf_backend.PdfPages(str(output_pdf)) as pdf_out:
        pdf_out.savefig(fig, bbox_inches='tight')
    plt.close(fig)
    
    print("\nTHREAT ASSESSMENT RESULTS")
    print(df.to_string(index=False))
    print(f"\nPDF saved to: {output_pdf}")


def on_control_update(update_type, value):
    global current_conf, current_size, current_res
    if update_type == 'confidence':
        current_conf = value
        detector.set_confidence(value)
        print(f"Detection confidence set to {value}")
    elif update_type == 'imgsz':
        current_size = value
        detector.set_image_size(value)
        print(f"Detection image size set to {value}")
    elif update_type == 'resolution':
        current_res = value
        enhancer.set_resolution(value)
        print(f"Enhancement resolution set to {value}")


def main():
    global detector, enhancer, current_conf, current_size, current_res
    
    print("Testing camera...")
    test_cap = cv2.VideoCapture(0)
    if not test_cap.isOpened():
        print("Camera index 0 failed, trying index 1...")
        test_cap = cv2.VideoCapture(1)
    if not test_cap.isOpened():
        print("No camera found. Exiting.")
        return
    test_cap.release()
    
    cv2.namedWindow("Live Feed", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("Live Feed", 1280, 720)
    
    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
    if not cap.isOpened():
        cap = cv2.VideoCapture(1)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
    if not cap.isOpened():
        print("No camera found.")
        return
    
    print("Camera opened successfully. Press 'q' to quit.")
    
    enhancer = UnderwaterEnhancer()
    detector = CrabDetector()
    collector = FrameCollector()
    
    current_conf = 0.5
    current_size = 1600
    current_res = "640x480"
    
    view_mode = "normal"
    
    print("\n=== CONTROLS ===")
    print("f - Frequency Analysis (opens PDF selector)")
    print("t - Threat Assessment (opens PDF selector)")
    print("u - Toggle Underwater Enhancement ON/OFF")
    print("d - Toggle Object Detection ON/OFF (prints green crab count when changed)")
    print("s - Start 3D capture (sharp + different frames only)")
    print("e - Stop 3D capture")
    print("c - Capture single frame")
    print("q - Quit")
    print("=" * 30)
    
    settings = SettingsPanel()
    settings.set_callback(on_control_update)
    settings_thread = threading.Thread(target=settings.show, daemon=True)
    settings_thread.start()
    
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        
        collector.process(frame)
        original = frame.copy()
        
        if view_mode == "normal":
            display = frame
        elif view_mode == "enhancement":
            display = enhancer.enhance(frame)
        elif view_mode == "detection":
            display, green_count, other_count = detector.detect(frame)
            cv2.putText(display, f"Green crabs: {green_count}", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
            cv2.putText(display, f"Other crabs: {other_count}", (10, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
        
        cv2.imshow("Live Feed", display)
        
        key = cv2.waitKey(1) & 0xFF
        
        if key == ord('q'):
            break
        
        elif key == ord('f'):
            cv2.destroyWindow("Live Feed")
            analyze_frequency()
            cv2.namedWindow("Live Feed", cv2.WINDOW_NORMAL)
            cv2.resizeWindow("Live Feed", 1280, 720)
        
        elif key == ord('t'):
            cv2.destroyWindow("Live Feed")
            assess_threat()
            cv2.namedWindow("Live Feed", cv2.WINDOW_NORMAL)
            cv2.resizeWindow("Live Feed", 1280, 720)
        
        elif key == ord('u'):
            if view_mode == "enhancement":
                view_mode = "normal"
                print("Underwater Enhancement OFF")
            else:
                view_mode = "enhancement"
                print("Underwater Enhancement ON")
        
        elif key == ord('d'):
            if view_mode == "detection":
                view_mode = "normal"
                print("Object Detection OFF")
            else:
                view_mode = "detection"
                print("Object Detection ON")
        
        elif key == ord('s'):
            collector.start()
        
        elif key == ord('e'):
            collector.stop()
        
        elif key == ord('c'):
            cv2.destroyWindow("Live Feed")
            captured = original.copy()
            cv2.imshow("Captured Frame", captured)
            cv2.waitKey(500)
            
            print("\n=== CAPTURED FRAME OPTIONS ===")
            print("1 - Perspective Transform (drag corners)")
            print("2 - Underwater Enhancement")
            print("3 - Object Detection")
            print("4 - Save")
            print("5 - Discard")
            print("================================")
            
            done = False
            current_image = captured.copy()
            
            while not done:
                sub_key = cv2.waitKey(0) & 0xFF
                
                if sub_key == ord('1'):
                    editor = PerspectiveEditor(current_image)
                    result = editor.run()
                    if result is not None:
                        current_image = result
                        cv2.imshow("Transformed", current_image)
                        cv2.waitKey(500)
                        print("Perspective transform applied.")
                    else:
                        print("Transform cancelled.")
                
                elif sub_key == ord('2'):
                    enhanced = enhancer.enhance(current_image)
                    current_image = enhanced
                    cv2.imshow("Enhanced", current_image)
                    cv2.waitKey(500)
                    print("Underwater enhancement applied.")
                
                elif sub_key == ord('3'):
                    detected, green_count, other_count = detector.detect(current_image)
                    current_image = detected
                    cv2.imshow("Detection Result", current_image)
                    cv2.waitKey(500)
                    print(f"Object detection applied. Green crabs: {green_count}, Other crabs: {other_count}")
                
                elif sub_key == ord('4'):
                    timestamp = time.strftime("%Y%m%d_%H%M%S")
                    filename = collector.save_folder / f"processed_{timestamp}.jpg"
                    cv2.imwrite(str(filename), current_image)
                    print(f"Saved: {filename}")
                    done = True
                
                elif sub_key == ord('5'):
                    print("Image discarded.")
                    done = True
            
            cv2.destroyAllWindows()
            cv2.namedWindow("Live Feed", cv2.WINDOW_NORMAL)
            cv2.resizeWindow("Live Feed", 1280, 720)
    
    cap.release()
    cv2.destroyAllWindows()
    print("Program terminated.")


if __name__ == "__main__":
    main()