import os
import threading
import subprocess
import urllib.parse
import urllib.request
import configparser
import tempfile
import tkinter as tk
from tkinter import ttk, messagebox
import xml.etree.ElementTree as ET
import time
from functools import partial
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

# ---------------------------
#Defaults
# ---------------------------
DEFAULT_CONF_FILE = "pelican.conf"
DEFAULTS = {
    "credentials": {"username": "mymail@gmail.com", "password": "password"},
    "api": {"base_url": "https://mysites.officeclimatecontrol.net/api.cgi"},
    "site": {"altname": "Alt Name"},
    "zones": {"Thermostat 1": "Zone 1"},
    "ui": {"last_zone": ""}
}
# Fields often requested together (single source of truth)
ALL_FIELDS = "description;system;fan;slaves;runstatus;temperature;humidity;heatsetting;coolsetting;frontkeypad;schedule;serialno;"

# ---------------------------
# Helper utilities
# ---------------------------


def ensure_config_exists(path=DEFAULT_CONF_FILE):
    """Ensure a config file exists with defaults (create only if missing)."""
    if not os.path.exists(path):
        cfg = configparser.ConfigParser()
        for section, values in DEFAULTS.items():
            cfg[section] = values
        try:
            with open(path, "w") as f:
                cfg.write(f)
            print(f"📝 Created default config at {path}")
        except Exception as e:
            print(f"⚠️ Failed to create config: {e}")



def load_config(path=DEFAULT_CONF_FILE):
    """
    Load configuration. IMPORTANT: do not create or overwrite the config file here.
    Creation is handled only by ensure_config_exists so defaults are written only
    if the file did not previously exist.
    """
    config = configparser.ConfigParser()
    # Seed defaults in-memory so missing sections/keys won't raise later
    for section, values in DEFAULTS.items():
        config[section] = values.copy()
    try:
        if os.path.exists(path):
            config.read(path)
        # NOTE: do NOT create the file here. keep creation only in ensure_config_exists.
    except Exception as e:
        print(f"Error reading config: {e}")
    return config


def save_config(config, path=DEFAULT_CONF_FILE):
    try:
        with open(path, "w") as f:
            config.write(f)
    except Exception as e:
        print(f"Failed to save config: {e}")


# ---------------------------
# Networking / PowerShell invoker
# ---------------------------


class APIInvoker:
    """Encapsulate the HTTP invocation. Prefer PowerShell on Windows, fallback to urllib."""

    def __init__(self, base_url, username, password, timeout=30):
        self.base_url = base_url
        self.username = username
        self.password = password
        self.timeout = timeout

    def build_url(self, params: dict) -> str:
        """Build a URL with URL-encoded params."""
        encoded = "&".join(f"{k}={urllib.parse.quote_plus(str(v))}" for k, v in params.items())
        return f"{self.base_url}?{encoded}"

    def invoke(self, request_type: str, value: str, zone_name: str = None) -> (bool, str):
        """
        Invoke the API. Returns tuple (success: bool, text: str).
        On Windows, attempt PowerShell Invoke-WebRequest to keep consistent behavior.
        If PowerShell isn't available or on non-windows, fallback to urllib.request.
        """
        params = {
            "username": self.username,
            "password": self.password,
            "request": request_type,
            "object": "Thermostat",
        }

        if zone_name:
            # selection param expects 'name:Zone Name;'
            params["selection"] = f"name:{zone_name};"
        # value param passed raw
        params["value"] = value

        url = self.build_url(params)

        # If running on Windows, attempt PowerShell for parity with previous behavior
        if os.name == "nt":
            try:
                # Use single-quoted URI to reduce escaping issues
                ps_command = f"(Invoke-WebRequest -Uri '{url}' -UseBasicParsing).Content"
                result = subprocess.run(
                    ["powershell", "-Command", ps_command],
                    capture_output=True,
                    text=True,
                    timeout=self.timeout,
                )
                if result.returncode == 0:
                    return True, result.stdout
                else:
                    # include stderr when available
                    return False, result.stderr or result.stdout
            except FileNotFoundError:
                # PowerShell not found — fall through to urllib
                pass
            except subprocess.TimeoutExpired:
                return False, "Request timed out (PowerShell)."
            except Exception as ex:
                return False, f"PowerShell invocation failed: {ex}"

        # Fallback to urllib
        try:
            with urllib.request.urlopen(url, timeout=self.timeout) as resp:
                text = resp.read().decode(errors="replace")
                return True, text
        except Exception as e:
            return False, f"urllib request failed: {e}"


# ---------------------------
# XML Parsing utility
# ---------------------------


def safe_parse_xml(text: str) -> ET.Element:
    """
    Safely parse XML text and return an Element root.
    If the response is a fragment (no single root), wrap it in a fake root.
    Raises ET.ParseError if content isn't XML.
    """
    text = (text or "").strip()
    if not text.startswith("<"):
        # Not XML
        raise ET.ParseError("Not XML content")
    # Try direct parse, else wrap with a root
    try:
        root = ET.fromstring(text)
        return root
    except ET.ParseError:
        wrapped = f"<root>{text}</root>"
        root = ET.fromstring(wrapped)
        return root


def extract_values_from_xml(root: ET.Element) -> dict:
    """
    Walk the element tree and collect a mapping of tag -> last text found (lowercased tag).
    For repeated tags (like <name> under <slaves>), keep a list in a special 'slaves' entry.
    """
    data = {}
    # Flatten simple tags
    for elem in root.iter():
        tag = (elem.tag or "").lower()
        text = elem.text.strip() if elem.text else ""
        if not tag:
            continue
        if tag in data and isinstance(data[tag], list):
            data[tag].append(text)
        elif tag in data:
            data[tag] = [data[tag], text]
        else:
            data[tag] = text
    return data


# ---------------------------
# GUI Class
# ---------------------------


class ThermostatControlGUI:
    def __init__(self, root, conf_path=DEFAULT_CONF_FILE):
        self.root = root
        self.root.title("Pelican Wireless Controls")
        self.root.geometry("880x740")
        self.root.configure(bg="#2c3e50")
        self.conf_path = conf_path

        # Load config: ensure file exists (create defaults only if missing), then load.
        ensure_config_exists(conf_path)
        self.config = load_config(conf_path)

        # Credentials & API
        self.username = self.config.get("credentials", "username", fallback=DEFAULTS["credentials"]["username"])
        self.password = self.config.get("credentials", "password", fallback=DEFAULTS["credentials"]["password"])
        self.base_url = self.config.get("api", "base_url", fallback=DEFAULTS["api"]["base_url"])

        # Zones: keys are display names (e.g., 'Thermostat 1') and values are actual thermostat names (Zone 1)
        self.zones = {}
        if "zones" in self.config:
            for k in self.config["zones"]:
                self.zones[k] = self.config["zones"][k]
        if not self.zones:
            self.zones = DEFAULTS["zones"]

        # Site name and altname
        self.site_name = "Climate Control"
        self.altname = self.config.get("site", "altname", fallback=DEFAULTS["site"]["altname"])

        # API invoker
        self.api = APIInvoker(self.base_url, self.username, self.password)

        # Setup styles
        self.style = ttk.Style()
        try:
            self.style.theme_use("clam")
        except Exception:
            # fallback if theme not available
            pass
        self._configure_styles()

        # Build GUI
        self._build_gui()

        # Try to restore last zone selection
        last_zone = self.config.get("ui", "last_zone", fallback="")
        if last_zone and last_zone in self.zones:
            self.zone_var.set(last_zone)
        else:
            # default to first zone key
            first = next(iter(self.zones.keys()))
            self.zone_var.set(first)

        # Non-blocking fetch of site name & auto set altname if needed
        self.root.after(300, self.fetch_site_name_threaded)
        if self.altname:
            self.root.after(1200, lambda: self.set_altname_if_needed(self.altname))

        # Bind close
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        # Initial message
        self.log_info("🚀 Climate Control System Ready")
        self.log_info("=" * 60)

    # ---------------------------
    # Styles & UI helpers
    # ---------------------------
    def _configure_styles(self):
        self.style.configure("TFrame", background="#2c3e50")
        self.style.configure("TLabel", background="#2c3e50", foreground="white", font=("Arial", 10))
        self.style.configure("Title.TLabel", font=("Arial", 18, "bold"), foreground="#ecf0f1", background="#2c3e50")
        self.style.configure("TButton", font=("Arial", 10, "bold"), padding=6)
        self.style.configure("Primary.TButton", background="#000000", foreground="white")
        self.style.configure("Secondary.TButton", background="#5b5b5b", foreground="white")
        self.style.configure("Success.TButton", background="#3498db", foreground="white")
        self.style.configure("TCombobox", padding=5)
        self.style.configure("TScrollbar", background="#34495e")
        self.style.configure("Heating.TButton", background="#cc0000", foreground="white")
        self.style.configure("live.TButton", background="#27ae60", foreground="white")

        # Hover/active styles (map)
        self.style.map(
            "Primary.TButton",
            background=[("active", "#000000"), ("pressed", "#1f618d")],
        )
        self.style.map(
            "Secondary.TButton",
            background=[("active", "#000000"), ("pressed", "#922b21")],
        )
        self.style.map(
            "Success.TButton",
            background=[("active", "#000000"), ("pressed", "#229954")],
        )
        self.style.map(
            "live.TButton",
            background=[("active", "#000000"), ("pressed", "#1f618d")],
        )
        self.style.map(
            "Heating.TButton",
            background=[("active", "#000000"), ("pressed", "#1f618d")],
        )

    

    # ---------------------------
    # GUI Building
    # ---------------------------
    def _build_gui(self):
        main_container = ttk.Frame(self.root)
        main_container.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        main_container.columnconfigure(0, weight=1)
        main_container.rowconfigure(3, weight=1)

        # Logo area (try to download)
        try:
            image_url = "https://www.pelicanwireless.com/wp-content/uploads/2018/07/Pelican-Logo-Color.png"
            with urllib.request.urlopen(image_url, timeout=6) as r:
                data = r.read()
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
            tmp.write(data)
            tmp.close()
            self.logo_image = tk.PhotoImage(file=tmp.name)
            logo_frame = ttk.Frame(main_container)
            logo_frame.grid(row=0, column=0, pady=(8, 6))
            ttk.Label(logo_frame, image=self.logo_image).pack()
            # schedule removal of temp file
            self.root.after(4000, lambda: os.unlink(tmp.name) if os.path.exists(tmp.name) else None)
        except Exception:
            # fallback text logo
            logo_frame = ttk.Frame(main_container)
            logo_frame.grid(row=0, column=0, pady=(8, 6))
            ttk.Label(logo_frame, text="🐦 PELICAN WIRELESS", style="Title.TLabel").pack()

        # Site title under logo
        site_frame = ttk.Frame(main_container)
        site_frame.grid(row=1, column=0, pady=(0, 8), sticky="n")
        self.title_label = ttk.Label(site_frame, text=f"Site - {self.site_name}", style="Title.TLabel")
        self.title_label.pack()

        # Header / spacer
        header_frame = ttk.Frame(main_container)
        header_frame.grid(row=2, column=0, sticky=(tk.W, tk.E), pady=(0, 6))

        # Content frame
        content_frame = ttk.Frame(main_container, padding=12)
        content_frame.grid(row=3, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        content_frame.columnconfigure(0, weight=1)
        content_frame.rowconfigure(1, weight=1)
        

        # Control panel
        control_frame = ttk.LabelFrame(content_frame, text="🧭 Control Panel", padding=12)
        control_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        

        # Zone selection
        zone_frame = ttk.Frame(control_frame)
        zone_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(4, 10))
        ttk.Label(zone_frame, text=" 🌡️ Select Zone:", font=("Arial", 11, "bold")).grid(row=0, column=0, sticky=tk.W)

        graph_button = ttk.Button(zone_frame, text="📈 Show Live Graph", style="live.TButton",
                          command=self.show_live_graph)
        graph_button.grid(row=0, column=2, padx=(10, 0), sticky=tk.E)
        
        self.zone_var = tk.StringVar()
        zone_combo = ttk.Combobox(
            zone_frame,
            textvariable=self.zone_var,
            values=list(self.zones.keys()),
            state="readonly",
            width=26,
            font=("Arial", 10),
        )
        zone_combo.grid(row=0, column=1, padx=10, sticky=(tk.W))
        zone_combo.bind("<<ComboboxSelected>>", self.on_zone_selected)

        # Buttons grid
        btn_grid = ttk.Frame(control_frame)
        btn_grid.grid(row=1, column=0, pady=(6, 0), sticky=(tk.W, tk.E))

        buttons = [
            ("ℹ️ Get All Info", "Primary.TButton", partial(self.get_all_info_threaded)),
            ("⚙️ Set System", "Secondary.TButton", partial(self.open_simple_selection_dialog, "System Mode", ["Off", "Heat", "Cool", "Auto"], "system", "set")),
            ("💫 Set Fan", "Secondary.TButton", partial(self.open_simple_selection_dialog, "Fan Mode", ["Auto", "On"], "fan", "set")),
            ("❄️ Set Cooling", "Success.TButton", partial(self.open_temperature_dialog, "cool")),
            ("☀️ Set Heating", "Heating.TButton", partial(self.open_temperature_dialog, "heat")),
            ("⚙️ Edit Config", "Secondary.TButton", self.edit_config_dialog),
        ]

        for i, (text, style, cmd) in enumerate(buttons):
            b = ttk.Button(btn_grid, text=text, style=style, command=cmd, width=16)
            b.grid(row=0, column=i, padx=4, pady=4)

        # Results pane
        results_frame = ttk.LabelFrame(content_frame, text="📋 System Response", padding=8)
        results_frame.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(10, 0))
        results_frame.columnconfigure(0, weight=1)
        results_frame.rowconfigure(0, weight=1)

        text_frame = ttk.Frame(results_frame)
        text_frame.grid(row=0, column=0, sticky=(tk.N, tk.S, tk.W, tk.E))
        text_frame.columnconfigure(0, weight=1)
        text_frame.rowconfigure(0, weight=1)

        self.result_text = tk.Text(
            text_frame,
            height=18,
            wrap=tk.WORD,
            font=("Consolas", 10),
            bg="#ecf0f1",
            fg="#2c3e50",
            relief=tk.FLAT,
            bd=2,
            padx=8,
            pady=8,
        )
        self.result_text.grid(row=0, column=0, sticky=(tk.N, tk.S, tk.W, tk.E))

        scrollbar = ttk.Scrollbar(text_frame, orient=tk.VERTICAL, command=self.result_text.yview)
        scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))
        self.result_text.configure(yscrollcommand=scrollbar.set)

        # Text tags for coloring
        self.result_text.tag_config("INFO", foreground="#2c3e50")
        self.result_text.tag_config("WARN", foreground="#b35e00")
        self.result_text.tag_config("ERROR", foreground="#c0392b")
        self.result_text.tag_config("DEBUG", foreground="#34495e")

        # Status bar
        status_frame = ttk.Frame(content_frame)
        status_frame.grid(row=2, column=0, sticky=(tk.W, tk.E))
        self.status_var = tk.StringVar(value="✅ Ready - Select a zone and click an action")
        status_label = ttk.Label(status_frame, textvariable=self.status_var, relief=tk.FLAT, padding=6, background="#34495e", foreground="white", font=("Arial", 9))
        status_label.pack(fill=tk.X)
        
    def show_live_graph(self):
        import matplotlib.pyplot as plt
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

        zone_key = self.zone_var.get()
        zone_name = self.zones.get(zone_key, zone_key)

        graph_window = tk.Toplevel(self.root)
        graph_window.title(f"Live Graph - {zone_key}")
        graph_window.geometry("700x450")

        fig, ax = plt.subplots(figsize=(7, 4))
        canvas = FigureCanvasTkAgg(fig, master=graph_window)
        canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        # Data lists
        times, temp_data, discharge_data, cool_data, heat_data = [], [], [], [], []
        after_id = None  # store after job id

        def update_graph():
            nonlocal times, temp_data, discharge_data, cool_data, heat_data, after_id

            success, resp = self.api.invoke("get", ALL_FIELDS, zone_name)
            if success:
                try:
                    root_xml = safe_parse_xml(resp)
                    vals = extract_values_from_xml(root_xml)

                    timestamp = time.strftime("%H:%M:%S")
                    times.append(timestamp)
                    temp_data.append(float(vals.get("temperature", 0)))
                    discharge_data.append(float(vals.get("value", 0)))
                    cool_data.append(float(vals.get("coolsetting", 0)))
                    heat_data.append(float(vals.get("heatsetting", 0)))

                    # keep last 40 points
                    if len(times) > 40:
                        times = times[-40:]
                        temp_data = temp_data[-40:]
                        discharge_data = discharge_data[-40:]
                        cool_data = cool_data[-40:]
                        heat_data = heat_data[-40:]

                    ax.clear()
                    ax.plot(times, temp_data, label="Temperature", marker='o', color='green')
                    ax.plot(times, discharge_data, label="Discharge Temp", marker='o', color='orange')
                    ax.plot(times, cool_data, label="Cool Setting", marker='x', color='blue')
                    ax.plot(times, heat_data, label="Heat Setting", marker='x', color='red')
                    ax.set_title(f"Live Zone Data: {zone_key}")
                    ax.set_xlabel("Time")
                    ax.set_ylabel("Value")
                    ax.grid(True)
                    ax.legend()
                    canvas.draw()
                except Exception as e:
                    self.log_info(f"Graph Update Error: {e}")
            else:
                self.log_info(f"Graph API error: {resp}")

            # Schedule next update if window still exists
            if graph_window.winfo_exists():
                after_id = graph_window.after(20000, update_graph)  # 20 sec

        # Start updates
        update_graph()

        # Cancel updates when window closes
        def on_close():
            if after_id:
                graph_window.after_cancel(after_id)
            graph_window.destroy()
        graph_window.protocol("WM_DELETE_WINDOW", on_close)

    # ---------------------------
    # Logging helpers
    # ---------------------------
    def _insert_text(self, text, tag="INFO"):
        timestamp = time.strftime("%H:%M:%S")
        self.result_text.insert(tk.END, f"[{timestamp}] {text}\n", tag)
        self.result_text.see(tk.END)

    def log_info(self, text):
        self._insert_text(text, "INFO")
        # keep status aligned
        self.status_var.set(text if len(text) < 80 else text[:78] + "...")

    def log_warn(self, text):
        self._insert_text(text, "WARN")
        self.status_var.set("⚠ " + (text if len(text) < 60 else text[:58] + "..."))

    def log_error(self, text):
        self._insert_text(text, "ERROR")
        self.status_var.set("❌ " + (text if len(text) < 60 else text[:58] + "..."))

    # ---------------------------
    # Config editing
    # ---------------------------
    def edit_config_dialog(self):
        """Open configuration file for manual editing (default editor)."""
        config_file = self.conf_path
        if not os.path.exists(config_file):
            messagebox.showerror("Error", f"Config file {config_file} not found!")
            return
        try:
            if os.name == "nt":
                os.startfile(config_file)
            else:
                # macOS or Linux fallback
                try:
                    if hasattr(os, "uname") and os.uname().sysname == "Darwin":
                        subprocess.run(["open", config_file])
                    else:
                        subprocess.run(["xdg-open", config_file])
                except Exception:
                    # As a last resort, open in vi/nano in terminal
                    subprocess.run(["xdg-open", config_file])
            self.log_info("⚙️ Config file opened for editing - restart to apply changes")
        except Exception as e:
            messagebox.showerror("Error", f"Unable to open config: {e}")

    # ---------------------------
    # Zone selection handling
    # ---------------------------
    def on_zone_selected(self, event=None):
        """When the user changes zone, fetch data for that zone with a small debounce."""
        selected = self.zone_var.get()
        if selected:
            # Save last zone immediately to config
            try:
                if "ui" not in self.config:
                    self.config["ui"] = {}
                self.config["ui"]["last_zone"] = selected
                save_config(self.config, self.conf_path)
            except Exception:
                pass
            self.status_var.set(f"🔄 Loading data for {selected}...")
            # small delay to prevent immediate repeated calls
            self.root.after(120, self.get_all_info_threaded)

    # ---------------------------
    # Threaded requests & processing
    # ---------------------------
    def get_all_info_threaded(self):
        """Convenience wrapper to request all fields."""
        self._threaded_request("get", ALL_FIELDS)

    def _threaded_request(self, request_type: str, value: str):
        """Spawn a thread to perform the API request and update UI when done."""
        zone_key = self.zone_var.get()
        zone_name = self.zones.get(zone_key, zone_key)

        self.status_var.set(f"Making {request_type} request for {zone_key}...")
        self.result_text.delete(1.0, tk.END)

        def worker():
            success, response_text = self.api.invoke(request_type, value, zone_name=zone_name)
            if success:
                # Try to parse XML and format
                try:
                    root = safe_parse_xml(response_text)
                    data = extract_values_from_xml(root)
                    pretty = self._format_data_for_display(data, value)
                    self.root.after(0, lambda: self._display_response(pretty, request_type, zone_key))
                except ET.ParseError:
                    # Non-XML responses handled as raw
                    self.root.after(0, lambda: self._display_error(f"Invalid XML returned. Raw output:\n{response_text[:200]}..."))
            else:
                # error
                self.root.after(0, lambda: self._display_error(response_text))

        t = threading.Thread(target=worker, daemon=True)
        t.start()

    def _display_response(self, text: str, request_type: str, zone_key: str):
        self.result_text.insert(tk.END, text + "\n")
        self.result_text.see(tk.END)
        self.status_var.set(f"{request_type.capitalize()} request completed for {zone_key}")

    def _display_error(self, text: str):
        self.result_text.insert(tk.END, f"Error: {text}\n", "ERROR")
        self.result_text.see(tk.END)
        self.status_var.set("Request failed")

    # ---------------------------
    # Response formatting
    # ---------------------------
    def _format_data_for_display(self, data: dict, requested_values: str) -> str:
        """Create a human-friendly representation of parsed xml data."""
        lines = []
        rv = requested_values.lower()
        def has(key): return key in data and data[key] not in (None, "")

        if "description" in rv and has("description"):
            lines.append(f"Description:    {data.get('description')}")
        if "system" in rv and has("system"):
            lines.append(f"System:         {data.get('system')}")
        if "fan" in rv and has("fan"):
            lines.append(f"Fan:            {data.get('fan')}")
        if "runstatus" in rv and has("runstatus"):
            lines.append(f"Run Status:     {data.get('runstatus')}")
        if "temperature" in rv and has("temperature"):
            lines.append(f"Temperature:    {data.get('temperature')}°")
        if "humidity" in rv and has("humidity"):
            lines.append(f"Humidity:       {data.get('humidity')}%")
        if "slaves" in data:
            lines.append(f"Discharge Temp: {data.get('value')}°")     
        if "heatsetting" in rv and has("heatsetting"):
            lines.append(f"Heat Setting:   {data.get('heatsetting')}°")
        if "coolsetting" in rv and has("coolsetting"):
            lines.append(f"Cool Setting:   {data.get('coolsetting')}°")
        if "frontkeypad" in rv and has("frontkeypad"):
            lines.append(f"FrontKeypad:    {data.get('frontkeypad')}")
        if "schedule" in rv and has("schedule"):
            lines.append(f"Schedule:       {data.get('schedule')}")
        if "serialno" in rv and has("serialno"):
            lines.append(f"SerialNo:       {data.get('serialno')}")
        if "message" in data:
            lines.append(f"Message:        {data.get('message')}")
   

        
                    

        if not lines:
            # fallback to show some of the raw dictionary content
            if data:
                for k, v in sorted(data.items()):
                    disp = v if isinstance(v, str) and len(v) < 300 else (str(v)[:300] + "...")
                    lines.append(f"{k.capitalize():15}: {disp}")
            else:
                lines.append("No data returned by server.")

        return "\n".join(lines)

    # ---------------------------
    # Site name functions
    # ---------------------------
    def fetch_site_name_threaded(self):
        """Fetch site name using the API (get Site altname) without blocking GUI."""
        def worker():
            # Construct url manually here for site object
            params = {
                "username": self.username,
                "password": self.password,
                "request": "get",
                "object": "Site",
                "value": "altname",
            }
            url = self.api.build_url(params)
            # Try PowerShell on Windows; else urllib
            if os.name == "nt":
                try:
                    ps_command = f"(Invoke-WebRequest -Uri '{url}' -UseBasicParsing).Content"
                    result = subprocess.run(["powershell", "-Command", ps_command], capture_output=True, text=True, timeout=10)
                    if result.returncode == 0:
                        out = result.stdout
                        try:
                            root = safe_parse_xml(out)
                            alt = None
                            for elem in root.iter():
                                if (elem.tag or "").lower() == "altname" and elem.text:
                                    alt = elem.text.strip()
                                    break
                            if alt:
                                self.root.after(0, lambda: self._set_site_name(alt))
                                return
                        except ET.ParseError:
                            pass
                except Exception:
                    pass

            # fallback using urllib
            try:
                with urllib.request.urlopen(url, timeout=10) as r:
                    out = r.read().decode(errors="replace")
                try:
                    root = safe_parse_xml(out)
                    alt = None
                    for elem in root.iter():
                        if (elem.tag or "").lower() == "altname" and elem.text:
                            alt = elem.text.strip()
                            break
                    if alt:
                        self.root.after(0, lambda: self._set_site_name(alt))
                except ET.ParseError:
                    pass
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True).start()

    def _set_site_name(self, name):
        self.site_name = name
        self.title_label.config(text=f"Site - {self.site_name}")
        self.log_info(f"Connected to site: {self.site_name}")

    def set_altname_if_needed(self, altname):
        current_name = (self.site_name or "").strip().lower()
        default_names = {"", "climate control", "untitled", "default", "new site", "no name", "unknown", "none", "null"}
        if current_name in default_names:
            self.log_info(f"Setting site name to: {altname}")
            self.set_altname_threaded(altname)
        else:
            self.log_info(f"Site name already set to: {self.site_name}")

    def set_altname_threaded(self, altname):
        """Call Site set request to set altname."""
        def worker():
            params = {
                "username": self.username,
                "password": self.password,
                "request": "set",
                "object": "Site",
                "value": f"altname:{altname}"
            }
            url = self.api.build_url(params)
            if os.name == "nt":
                try:
                    ps_command = f"(Invoke-WebRequest -Uri '{url}' -UseBasicParsing).Content"
                    result = subprocess.run(["powershell", "-Command", ps_command], capture_output=True, text=True, timeout=10)
                    out = result.stdout if result.returncode == 0 else result.stderr
                except Exception as ex:
                    out = str(ex)
            else:
                try:
                    with urllib.request.urlopen(url, timeout=10) as r:
                        out = r.read().decode(errors="replace")
                except Exception as ex:
                    out = str(ex)
            # Check result for success
            try:
                root = safe_parse_xml(out)
                ok = False
                for elem in root.iter():
                    if (elem.tag or "").lower() == "success" and (elem.text or "").strip().lower() == "true":
                        ok = True
                        break
                if ok:
                    self.root.after(0, lambda: self._set_site_name(altname))
                    self.root.after(0, lambda: self.log_info(f"✅ Site name set to: {altname}"))
                else:
                    self.root.after(0, lambda: self.log_warn("Restart for site name to display"))
            except ET.ParseError:
                self.root.after(0, lambda: self.log_warn("Unexpected response when setting site name please make sure your config is set correctly"))

        threading.Thread(target=worker, daemon=True).start()

    # ---------------------------
    # Dialog Builders
    # ---------------------------
    def open_simple_selection_dialog(self, title: str, choices: list, value_key: str, request_type: str):
        """Generic dialog: choose from a list of choices; then send 'set' for key:value; refresh afterwards."""
        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.geometry("360x180")
        dialog.configure(bg="#2c3e50")
        dialog.transient(self.root)
        dialog.grab_set()

        ttk.Label(dialog, text=title, font=("Arial", 12, "bold"), foreground="white", background="#2c3e50").pack(pady=(12, 6))

        var = tk.StringVar(value=choices[0])
        combo = ttk.Combobox(dialog, textvariable=var, values=choices, state="readonly", width=18)
        combo.pack(pady=8)

        def confirm():
            sel = var.get()
            dialog.destroy()
            if sel:
                v = f"{value_key}:{sel};"
                self._threaded_request("set", v)
                # refresh after a short delay
                self.root.after(1200, self.get_all_info_threaded)

        btnf = ttk.Frame(dialog)
        btnf.pack(pady=(10, 8))
        ttk.Button(btnf, text="✅ OK", style="Success.TButton", command=confirm, width=12).pack(side=tk.LEFT, padx=6)
        ttk.Button(btnf, text="❌ Cancel", style="Secondary.TButton", command=dialog.destroy, width=12).pack(side=tk.LEFT, padx=6)
        dialog.wait_window()

    def open_temperature_dialog(self, mode: str):
        """Dialog to set heating or cooling temperature with a slider."""
        if mode.lower() not in ("heat", "cool"):
            return
        label = "Heating" if mode.lower() == "heat" else "Cooling"
        dialog = tk.Toplevel(self.root)
        dialog.title(f"Set {label} Temperature")
        dialog.geometry("420x220")
        dialog.configure(bg="#2c3e50")
        dialog.transient(self.root)
        dialog.grab_set()

        ttk.Label(dialog, text=f"Set {label} Temperature", font=("Arial", 12, "bold"), foreground="white", background="#2c3e50").pack(pady=(8, 6))

        temp_var = tk.IntVar(value=68 if mode.lower() == "heat" else 72)
        slider = ttk.Scale(dialog, from_=60, to=80, orient=tk.HORIZONTAL, variable=temp_var, length=300)
        slider.pack(pady=(8, 6))

        display = ttk.Label(dialog, text=f"{temp_var.get()}°", font=("Arial", 14, "bold"), foreground="#e74c3c" if mode.lower() == "heat" else "#3498db", background="#2c3e50")
        display.pack(pady=(4, 6))

        def update(*_):
            display.config(text=f"{temp_var.get()}°")

        temp_var.trace_add("write", update)

        def confirm():
            val = temp_var.get()
            dialog.destroy()
            key = "heatSetting" if mode.lower() == "heat" else "coolSetting"
            v = f"{key}:{val};"
            self._threaded_request("set", v)
            self.root.after(1200, self.get_all_info_threaded)

        btnf = ttk.Frame(dialog)
        btnf.pack(pady=(8, 6))
        ttk.Button(btnf, text="✅ Set Temperature", style="Success.TButton", command=confirm, width=16).pack(side=tk.LEFT, padx=6)
        ttk.Button(btnf, text="❌ Cancel", style="Secondary.TButton", command=dialog.destroy, width=12).pack(side=tk.LEFT, padx=6)

        dialog.wait_window()

    # ---------------------------
    # Close / persist state
    # ---------------------------
    def on_closing(self):
        """Save last chosen zone and other UI preferences back to config before exit."""
        try:
            if "ui" not in self.config:
                self.config["ui"] = {}
            self.config["ui"]["last_zone"] = self.zone_var.get()
            # Keep any existing credentials/api settings intact but overwrite with current ones
            if "credentials" not in self.config:
                self.config["credentials"] = {}
            self.config["credentials"]["username"] = self.username
            self.config["credentials"]["password"] = self.password
            if "api" not in self.config:
                self.config["api"] = {}
            self.config["api"]["base_url"] = self.base_url
            #save_config(self.config, self.conf_path)
        except Exception as e:
            print(f"Error saving config on close: {e}")
        if messagebox.askokcancel("Quit", "Do you want to quit?"):
            self.root.destroy()


# ---------------------------
# Main
# ---------------------------
def main():
    try:
        root = tk.Tk()
        app = ThermostatControlGUI(root)
        root.mainloop()
    except Exception as e:
        print(f"Fatal error: {e}")
        input("Press Enter to exit...")


if __name__ == "__main__":
    main()
