import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import subprocess
import re
import urllib.parse
import configparser
import os
import urllib.request
import tempfile
# Windows ONLY
class ThermostatControlGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Pelican Wireless Controls")
        self.root.geometry("900x780")
        self.root.configure(bg='#2c3e50')
        
        # Configure style
        self.style = ttk.Style()
        self.style.theme_use('clam')
        
        # Configure colors
        self.style.configure('TFrame', background='#2c3e50')
        self.style.configure('TLabel', background='#2c3e50', foreground='white', font=('Arial', 10))
        self.style.configure('Title.TLabel', font=('Arial', 18, 'bold'), foreground='#ecf0f1')
        self.style.configure('TButton', font=('Arial', 10, 'bold'), padding=8)
        self.style.configure('Primary.TButton', background='#000000', foreground='white')
        self.style.configure('Secondary.TButton', background='#5b5b5b', foreground='white')
        self.style.configure('Success.TButton', background='#3498db', foreground='white')
        self.style.configure('TCombobox', padding=5)
        self.style.configure('TScrollbar', background='#34495e')
        self.style.configure('Heating.TButton', background='#cc0000', foreground='white')
        
        # Load configuration from file
        self.config = configparser.ConfigParser()
        self.config.read('config.ini')
        self.config = self.load_config()
    
         # Set values from config
        self.username = self.config.get('credentials', 'username', fallback='')
        self.password = self.config.get('credentials', 'password', fallback='')
        self.base_url = self.config.get('api', 'base_url', fallback='https://mysites.officeclimatecontrol.net/api.cgi')
        
         # Load altname from config
        self.altname = self.config.get('site', 'altname', fallback='')
        
        
        # Load zones from config
        self.zones = {}
        
        if 'zones' in self.config:
            for zone_key in self.config['zones']:
                zone_name = self.config['zones'][zone_key]
                self.zones[zone_key] = zone_name
        else:
            # Fallback if no ZONES section exists
            print("Warning: No ZONES section found in config")
            self.zones = {'Thermostat 1': 'Zone 1'}  # Default single zone
        
        self.site_name = "Climate Control"  # Temporary name until we fetch the actual one
        
        self.setup_gui()
        # Fetch site name and set it only if not already set
        self.root.after(500, self.check_and_set_site_name)
        if self.altname:
            self.root.after(1000, lambda: self.set_altname_if_needed(self.altname))
    
    def load_config(self):
        """Load configuration from pelican.conf file"""
        config = configparser.ConfigParser()
        
        # Default configuration (fallback values)
        config['credentials'] = {
            'username': 'mymail@gmail.com',
            'password': 'password'
        }
        config['api'] = {
            'base_url': 'https://mysties.officeclimatecontrol.net/api.cgi'
        }
        config['site'] = {
            'altname': 'My Site Name'
        }
        # thermstat 1 is what you will see listed in the zone selection and Zone 1 is the name of the thermostat. Do not add to the list here but change it in the config file. The config file is located at your user folder and is called pelican.conf
        config['zones'] = {
            'Thermostat 1': 'Zone 1'
        }
        
        # Try to load from file
        config_file = 'pelican.conf'
        if os.path.exists(config_file):
            try:
                config.read(config_file)
                print(f"✅ Configuration loaded from {config_file}")
            except Exception as e:
                print(f"❌ Error reading config file: {e}")
        else:
            # Create default config file if it doesn't exist
            try:
                with open(config_file, 'w') as f:
                    config.write(f)
                print(f"📝 Created default configuration file: {config_file}")
            except Exception as e:
                print(f"❌ Error creating config file: {e}")
        
        return config

    def check_and_set_site_name(self):
        """Fetch current site name and set a new one only if not already set"""
        self.fetch_site_name()
    
    def set_altname_if_needed(self, altname):
        """Set the altname only if the current site name is empty or default"""
        # Check if the site name is empty or set to a default value
        current_name = self.site_name.strip().lower()
        
        # List of default/empty values that indicate no site name is set
        default_names = {
            "", "climate control", "untitled", "default", "new site", 
            "no name", "unknown", "none", "null"
        }
        
        if current_name in default_names:
            self.status_var.set(f"Setting site name to: {altname}")
            self.set_altname(altname)
        else:
            self.status_var.set(f"Site name already set to: {self.site_name}")
            self.result_text.insert(tk.END, f"\nℹ️ Site name already set to: {self.site_name}")
            self.result_text.see(tk.END)

    def set_altname(self, altname):
        """Set the altname for the site using the API"""
        try:
            # Build the API URL for setting altname
            params = [
                f"username={urllib.parse.quote_plus(self.username)}",
                f"password={urllib.parse.quote_plus(self.password)}",
                f"request=set",
                f"object=Site",
                f"value=altname:{urllib.parse.quote_plus(altname)}"
            ]
            url = f"{self.base_url}?{'&'.join(params)}"
            
            # Use PowerShell to make the request
            ps_command = f"(Invoke-WebRequest -Uri '{url}' -UseBasicParsing).Content"
            result = subprocess.run(['powershell', '-Command', ps_command], 
                                  capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                # Check if the request was successful
                success_match = re.search(r'<success>([^<]+)</success>', result.stdout)
                if success_match and success_match.group(1).lower() == 'true':
                    self.status_var.set(f"✅ Site name set to: {altname}")
                    self.site_name = altname
                    # Update the title label
                    self.title_label.config(text=f"Site - {self.site_name}")
                else:
                    self.status_var.set("❌ Failed to set site name")
            else:
                self.status_var.set("❌ Failed to set site name")
                
        except Exception as e:
            self.status_var.set(f"❌ Error setting site name: {str(e)}")

    def fetch_site_name(self):
        """Fetch site name from API and update title"""
        try:
            # Build the API URL for site name
            params = [
                f"username={urllib.parse.quote_plus(self.username)}",
                f"password={urllib.parse.quote_plus(self.password)}",
                f"request=get",
                f"object=Site",
                f"value=altname"
            ]
            url = f"{self.base_url}?{'&'.join(params)}"
            
            # Use PowerShell to make the request
            ps_command = f"(Invoke-WebRequest -Uri '{url}' -UseBasicParsing).Content"
            result = subprocess.run(['powershell', '-Command', ps_command], 
                                  capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                # Parse the XML response to get site name
                site_match = re.search(r'<altname>([^<]+)</altname>', result.stdout)
                if site_match:
                    self.site_name = site_match.group(1).strip()
                    # Add to debug output
                    self.result_text.insert(tk.END, f"\nCurrent site name: {self.site_name}")
                    self.result_text.see(tk.END)
                    # Update the title label
                    self.title_label.config(text=f"Site - {self.site_name}")
                    self.status_var.set(f"Connected to site: {self.site_name}")
                else:
                    self.status_var.set("Could not parse site name from response")
            else:
                self.status_var.set("Failed to fetch altname")
                
        except Exception as e:
            self.status_var.set(f"Error fetching site name: {str(e)}")

    def setup_gui(self):
        # Main container
        main_container = ttk.Frame(self.root)
        main_container.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # ADD LOGO AT THE VERY TOP
        try:
            # Download the image
            image_url = 'https://www.pelicanwireless.com/wp-content/uploads/2018/07/Pelican-Logo-Color.png'
            with urllib.request.urlopen(image_url) as response:
                image_data = response.read()
            
            # Save to temporary file
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.png')
            temp_file.write(image_data)
            temp_file.close()
            
            # Load image with tkinter
            self.logo_image = tk.PhotoImage(file=temp_file.name)
            
            # Create logo frame
            logo_frame = ttk.Frame(main_container)
            logo_frame.grid(row=0, column=0, pady=(10, 0), sticky='n')
            
            # Add logo label
            logo_label = ttk.Label(logo_frame, image=self.logo_image)
            logo_label.pack()
            
            # Clean up temp file
            self.root.after(3000, lambda: os.unlink(temp_file.name))
            
        except Exception as e:
            print(f"Couldn't load logo: {e}")
            # Fallback text logo
            logo_frame = ttk.Frame(main_container)
            logo_frame.grid(row=0, column=0, pady=(10, 0), sticky='n')
            
            logo_label = ttk.Label(logo_frame, text="🐦 PELICAN WIRELESS", 
                                  font=('Arial', 16, 'bold'), foreground='white')
            logo_label.pack()
        
        # SITE NAME DISPLAY - ADDED RIGHT UNDER LOGO
        site_frame = ttk.Frame(main_container)
        site_frame.grid(row=1, column=0, pady=(0, 10), sticky='n')
        
        self.title_label = ttk.Label(site_frame, text=f"Site - {self.site_name}", 
                                   style='Title.TLabel', foreground='black')
        self.title_label.pack()
        
        # Header - moved to row 2 to account for logo and site name
        header_frame = ttk.Frame(main_container)
        header_frame.grid(row=2, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 20))
        
        # Main content frame - moved to row 3
        content_frame = ttk.Frame(main_container, padding="20")
        content_frame.grid(row=3, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Control panel
        control_frame = ttk.LabelFrame(content_frame, text="🧭 Control Panel", padding="15")
        control_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 20))
        
        # Zone selection
        zone_frame = ttk.Frame(control_frame)
        zone_frame.grid(row=0, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 15))

        ttk.Label(zone_frame, text=" 🌡️Select Zone:", font=('Arial', 11, 'bold')).grid(row=0, column=0, sticky=tk.W)
        self.zone_var = tk.StringVar()
        zone_combo = ttk.Combobox(zone_frame, textvariable=self.zone_var, 
                                 values=list(self.zones.keys()), state="readonly",
                                 width=20, font=('Arial', 10))
        zone_combo.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=10)

        # Set the default to the first zone name
        if self.zones:
            first_zone_name = list(self.zones.keys())[0]
            zone_combo.set(first_zone_name)
        else:
            zone_combo.set("Select Zone")  # Fallback

        # Bind the selection event to automatically get info
        zone_combo.bind('<<ComboboxSelected>>', self.on_zone_selected)

        # Auto-load first zone after GUI is fully initialized
        self.root.after(500, self.on_zone_selected)

        
        # Action buttons
        button_grid = ttk.Frame(control_frame)
        button_grid.grid(row=1, column=0, columnspan=2, pady=10)
        
        buttons = [
            ("ℹ️Get All Info", 'Primary.TButton', 
             lambda: self.make_request("get", "description;system;fan;slaves;runstatus;temperature;humidity;heatsetting;coolsetting;frontkeypad;schedule;serialno;")),
            ("⚙️ Set System", 'Secondary.TButton', self.set_system_dialog),
            ("💫 Set Fan", 'Secondary.TButton', self.set_fan_dialog),
            ("❄️ Set Cooling", 'Success.TButton', lambda: self.set_temperature_dialog("cool")),
            ("☀️ Set Heating", 'Heating.TButton', lambda: self.set_temperature_dialog("heat")),
            ("⚙️ Edit Config", 'Secondary.TButton', self.edit_config_dialog)  # New button
        ]
        
        for i, (text, style, command) in enumerate(buttons):
            btn = ttk.Button(button_grid, text=text, command=command, style=style, width=15)
            btn.grid(row=0, column=i, padx=5, pady=5)
        
        # Results display
        results_frame = ttk.LabelFrame(content_frame, text="📋 System Response", padding="15")
        results_frame.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 20))
        
        # Text widget
        text_frame = ttk.Frame(results_frame)
        text_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        self.result_text = tk.Text(text_frame, height=15, width=80, wrap=tk.WORD, 
                                  font=('Consolas', 10), bg='#ecf0f1', fg='#2c3e50',
                                  relief=tk.FLAT, bd=2, padx=10, pady=10)
        self.result_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        scrollbar = ttk.Scrollbar(text_frame, orient=tk.VERTICAL, command=self.result_text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.result_text.configure(yscrollcommand=scrollbar.set)
        
        # Status bar
        status_frame = ttk.Frame(content_frame)
        status_frame.grid(row=2, column=0, sticky=(tk.W, tk.E))
        
        self.status_var = tk.StringVar()
        self.status_var.set("✅ Ready - Select a zone and click an action")
        status_bar = ttk.Label(status_frame, textvariable=self.status_var, 
                              relief=tk.FLAT, padding=8, background='#34495e', 
                              foreground='white', font=('Arial', 9))
        status_bar.pack(fill=tk.X)
        
        # Configure grid weights
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_container.columnconfigure(0, weight=1)
        main_container.rowconfigure(1, weight=1)
        content_frame.columnconfigure(0, weight=1)
        content_frame.rowconfigure(1, weight=1)
        results_frame.columnconfigure(0, weight=1)
        results_frame.rowconfigure(0, weight=1)
        
        # Bind window close event
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        # Initial message
        self.result_text.insert(tk.END, "🚀 Climate Control System Ready\n")
        self.result_text.insert(tk.END, "="*50 + "\n\n")
        
    def edit_config_dialog(self):
        """Open the configuration file for editing"""
        config_file = 'pelican.conf'
        
        if not os.path.exists(config_file):
            messagebox.showerror("Error", f"Config file {config_file} not found!")
            return
        
        try:
            # Open the config file with the default text editor
            if os.name == 'nt':  # Windows
                os.startfile(config_file)
            elif os.name == 'posix':  # macOS or Linux
                if os.uname().sysname == 'Darwin':  # macOS
                    subprocess.run(['open', config_file])
                else:  # Linux
                    subprocess.run(['xdg-open', config_file])
            
            self.status_var.set("⚙️ Config file opened for editing - restart to apply changes")
            
        except Exception as e:
            messagebox.showerror("Error", f"Could not open config file: {e}")
        
    def on_zone_selected(self, event=None):
        """Automatically get all info when a zone is selected"""
        selected_zone = self.zone_var.get()
        if selected_zone:
            self.status_var.set(f"🔄 Loading data for {selected_zone}...")
            self.root.update()
            
            # Small delay to prevent rapid fire requests (100ms)
            self.root.after(100, self.get_all_info)


    def perform_zone_update(self):
        """Perform the actual API request after a small delay"""
        self.make_request("get", "description;system;fan;slaves;runstatus;temperature;humidity;heatsetting;coolsetting;frontkeypad;schedule;serialno;")    
        
    def configure_button_styles(self):
        """Configure button hover effects"""
        self.style.map('Primary.TButton', 
                      background=[('active', '#2980b9'), ('pressed', '#1f618d')])
        self.style.map('Secondary.TButton', 
                      background=[('active', '#c0392b'), ('pressed', '#922b21')])
        self.style.map('Success.TButton', 
                      background=[('active', '#27ae60'), ('pressed', '#229954')])


    # Add these new methods for the setter buttons:
    def set_system_dialog(self):
        """Dialog to set system mode with dropdown selection"""
        modes = ["Off", "Heat", "Cool", "Auto"]
        
        # Create a themed dialog window
        dialog = tk.Toplevel(self.root)
        dialog.title("Set System Mode")
        dialog.geometry("350x220")
        dialog.configure(bg='#2c3e50')
        dialog.transient(self.root)
        dialog.grab_set()
        
        # Center the dialog
        dialog.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - dialog.winfo_width()) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - dialog.winfo_height()) // 2
        dialog.geometry(f"+{x}+{y}")
        
        # Main frame with styling
        main_frame = ttk.Frame(dialog, style='TFrame')
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        ttk.Label(main_frame, text="Select System Mode:", 
                 font=('Arial', 12, 'bold'), 
                 foreground='white').pack(pady=(10, 15))
        
        mode_var = tk.StringVar(value="Auto")
        mode_combo = ttk.Combobox(main_frame, textvariable=mode_var, 
                                 values=modes, state="readonly",
                                 width=12, font=('Arial', 11))
        mode_combo.pack(pady=10)
        
        def confirm_selection():
            selected_mode = mode_var.get()
            dialog.destroy()
            if selected_mode:
                self.make_request("set", f"system:{selected_mode};", callback=self.get_all_info)
        
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(pady=15)
        
        ttk.Button(button_frame, text="✅ OK", command=confirm_selection, 
                  style='Success.TButton', width=10).pack(side=tk.LEFT, padx=8)
        ttk.Button(button_frame, text="❌ Cancel", command=dialog.destroy,
                  style='Secondary.TButton', width=10).pack(side=tk.LEFT, padx=8)
        
        dialog.wait_window()

    def set_fan_dialog(self):
        """Dialog to set fan mode with dropdown selection"""
        modes = ["Auto", "On"]
        
        # Create a themed dialog window
        dialog = tk.Toplevel(self.root)
        dialog.title("Set Fan Mode")
        dialog.geometry("380x220")
        dialog.configure(bg='#2c3e50')
        dialog.transient(self.root)
        dialog.grab_set()
        
        # Center the dialog
        dialog.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - dialog.winfo_width()) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - dialog.winfo_height()) // 2
        dialog.geometry(f"+{x}+{y}")
        
        # Main frame with styling
        main_frame = ttk.Frame(dialog, style='TFrame')
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        ttk.Label(main_frame, text="Select Fan Mode:", 
                 font=('Arial', 12, 'bold'), 
                 foreground='white').pack(pady=(10, 15))
        
        mode_var = tk.StringVar(value="On")
        mode_combo = ttk.Combobox(main_frame, textvariable=mode_var, 
                                 values=modes, state="readonly",
                                 width=12, font=('Arial', 11))
        mode_combo.pack(pady=10)
        
        def confirm_selection():
            selected_mode = mode_var.get()
            dialog.destroy()
            if selected_mode:
                self.make_request("set", f"fan:{selected_mode};", callback=self.get_all_info)
        
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(pady=15)
        
        ttk.Button(button_frame, text="✅ OK", command=confirm_selection, 
                  style='Success.TButton', width=10).pack(side=tk.LEFT, padx=8)
        ttk.Button(button_frame, text="❌ Cancel", command=dialog.destroy,
                  style='Secondary.TButton', width=10).pack(side=tk.LEFT, padx=8)
        
        dialog.wait_window()


    def set_temperature_dialog(self, mode):
        """Dialog to set heating or cooling temperature with themed slider"""
        if mode.lower() not in ["heat", "cool"]:
            return
        
        # Create a themed dialog window
        dialog = tk.Toplevel(self.root)
        dialog.title(f"Set {'Heating' if mode.lower() == 'heat' else 'Cooling'} Temperature")
        dialog.geometry("400x250")
        dialog.configure(bg='#2c3e50')
        dialog.transient(self.root)
        dialog.grab_set()
        
        # Center the dialog
        dialog.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - dialog.winfo_width()) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - dialog.winfo_height()) // 2
        dialog.geometry(f"+{x}+{y}")
        
        # Main frame with styling
        main_frame = ttk.Frame(dialog, style='TFrame')
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        # Title
        title_text = f"Set {'Heating' if mode.lower() == 'heat' else 'Cooling'} Temperature"
        ttk.Label(main_frame, text=title_text, 
                 font=('Arial', 12, 'bold'), 
                 foreground='white').pack(pady=(0, 15))
        
        # Temperature slider
        temp_var = tk.IntVar(value=68 if mode.lower() == 'heat' else 72)
        
        # Slider frame
        slider_frame = ttk.Frame(main_frame)
        slider_frame.pack(pady=10)
        
        ttk.Label(slider_frame, text="60°", foreground='white').pack(side=tk.LEFT, padx=5)
        
        # Temperature slider with themed styling
        temp_slider = ttk.Scale(slider_frame, from_=60, to=80, orient=tk.HORIZONTAL,
                               variable=temp_var, length=250)
        temp_slider.pack(side=tk.LEFT, padx=10)
        
        ttk.Label(slider_frame, text="80°", foreground='white').pack(side=tk.LEFT, padx=5)
        
        # Current temperature display
        temp_display = ttk.Label(main_frame, text=f"{temp_var.get()}°", 
                                font=('Arial', 16, 'bold'), 
                                foreground='#e74c3c' if mode.lower() == 'heat' else '#3498db')
        temp_display.pack(pady=10)
    
        # Update display when slider moves
        def update_display(*args):
            temp_display.config(text=f"{temp_var.get()}°")
        
        temp_var.trace('w', update_display)
        
        def confirm_selection():
            selected_temp = temp_var.get()
            dialog.destroy()
            if selected_temp:
                if mode.lower() == "heat":
                    self.make_request("set", f"heatSetting:{selected_temp};", callback=self.get_all_info)
                else:
                    self.make_request("set", f"coolSetting:{selected_temp};", callback=self.get_all_info)
        
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(pady=15)
        
        ttk.Button(button_frame, text="✅ Set Temperature", command=confirm_selection, 
                  style='Success.TButton', width=15).pack(side=tk.LEFT, padx=8)
        ttk.Button(button_frame, text="❌ Cancel", command=dialog.destroy,
                  style='Secondary.TButton', width=10).pack(side=tk.LEFT, padx=8)
        
        dialog.wait_window()
    
    def on_closing(self):
        """Handle window closing"""
        if messagebox.askokcancel("Quit", "Do you want to quit?"):
            self.root.destroy()
    
    def build_api_url(self, request_type, value, zone_name=None):
        """Build the proper API URL with correct structure"""
        if zone_name is None:
            zone_name = self.zones[self.zone_var.get()]
        
        # Build parameters with proper encoding
        params = [
            f"username={urllib.parse.quote_plus(self.username)}",
            f"password={urllib.parse.quote_plus(self.password)}",
            f"request={request_type}",
            f"object=Thermostat",
            f"selection={urllib.parse.quote_plus(f'name:{zone_name};')}",
            f"value={urllib.parse.quote_plus(value)}"
        ]
        
        return f"{self.base_url}?{'&'.join(params)}"
    
    def make_request(self, request_type, value, callback=None):
        """Make API request using curl through PowerShell with optional callback"""
        zone = self.zone_var.get()
        self.status_var.set(f"Making {request_type} request for {zone}...")
        self.result_text.delete(1.0, tk.END)
        
        url = self.build_api_url(request_type, value)
        self.result_text.insert(tk.END, "="*50 + "\n")
        self.result_text.insert(tk.END, "Response:\n")
        self.root.update()
        
        try:
            # Use PowerShell with single quotes to avoid parsing issues
            ps_command = f"(Invoke-WebRequest -Uri '{url}' -UseBasicParsing).Content"
            result = subprocess.run(['powershell', '-Command', ps_command], 
                                  capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                cleaned_result = self.clean_xml_output(result.stdout, value)
                self.result_text.insert(tk.END, cleaned_result)
                
                # If this was a set command and we have a callback, run it
                if request_type.lower() == "set" and callback:
                    self.root.after(1000, callback)  # Wait 1 second then refresh
                
                self.status_var.set(f"{request_type.capitalize()} request completed for {zone}")
            else:
                error_msg = result.stderr if result.stderr else "Unknown error occurred"
                self.result_text.insert(tk.END, f"Error: {error_msg}")
                self.status_var.set("Request failed")
                
        except subprocess.TimeoutExpired:
            self.result_text.insert(tk.END, "Error: Request timed out after 30 seconds")
            self.status_var.set("Request timed out")
        except Exception as e:
            self.result_text.insert(tk.END, f"Error: {str(e)}")
            self.status_var.set("Request failed")
            
    def get_all_info(self):
        """Convenience method to get all thermostat info"""
        self.make_request("get", "description;system;fan;slaves;runstatus;temperature;humidity;heatsetting;coolsetting;frontkeypad;schedule;serialno;")        
    
    def clean_xml_output(self, xml_text, requested_values):
        """Clean XML output and format it nicely with descriptions"""
        clean_text = ""  # Initialize clean_text here
        try:
            # Parse the XML response
            data = {}
            
            # Extract all values between tags
            pattern = r'<([^>]+)>([^<]+)</\1>'
            matches = re.findall(pattern, xml_text)
            
            for tag, value in matches:
                data[tag.lower()] = value.strip()
            
            # Format the output based on what was requested
            output_lines = []
            
            if "description" in requested_values and "description" in data:
                output_lines.append(f"Description:    {data['description']}")
            
            if "system" in requested_values and "system" in data:
                output_lines.append(f"System:         {data['system']}")
            
            if "fan" in requested_values and "fan" in data:
                output_lines.append(f"Fan:            {data['fan']}")
            
            if "runstatus" in requested_values and "runstatus" in data:
                output_lines.append(f"Run Status:     {data['runstatus']}")
            
            if "temperature" in requested_values and "temperature" in data:
                output_lines.append(f"Temperature:    {data['temperature']}°")
             
            if "humidity" in requested_values and "humidity" in data:
                output_lines.append(f"Humidity:       {data['humidity']}%") 
            
            if "heatsetting" in requested_values and "heatsetting" in data:
                output_lines.append(f"Heat Setting:   {data['heatsetting']}°")
            
            if "coolsetting" in requested_values and "coolsetting" in data:
                output_lines.append(f"Cool Setting:   {data['coolsetting']}°")
                
            if "slaves" in requested_values:
                # Extract slave information from the raw XML
                slave_pattern = r'<name>([^<]+)</name>.*?<type>([^<]+)</type>.*?<value>([^<]+)</value>'
                slave_match = re.search(slave_pattern, xml_text, re.DOTALL)
            
                if slave_match:
                    name, stype, value = slave_match.groups()
                    output_lines.append(f"Discharge Temp: {value.strip()}°")    
            
            # Add success and message if available
            #if "success" in data:
            #    output_lines.append(f"\nSuccess:        {data['success']}")
            
            if "frontkeypad" in requested_values and "frontkeypad" in data:
                output_lines.append(f"FrontKeypad:    {data['frontkeypad']}")
                
            if "schedule" in requested_values and "schedule" in data:
                output_lines.append(f"Schedule:       {data['schedule']}")
                
            if "serialno" in requested_values and "serialno" in data:
                output_lines.append(f"SerialNo:       {data['serialno']}")        
            
            if "message" in data:
                output_lines.append(f"Message:        {data['message']}")
            
            # If no specific data found but we have a response, show raw cleaned text
            if not output_lines:
                cleaned_xml = re.sub(r'>\s+<', '><', xml_text)
                clean_text = re.sub(r'\s+', ' ', clean_text)
                clean_text = re.sub(r'\n\s*\n', '\n', clean_text)
                clean_text = clean_text.strip()
                output_lines.append(clean_text if clean_text else "No data received from server")
               
                
            return '\n'.join(output_lines)
            
        except Exception as e:
            return f"Error parsing response: {str(e)}\nRaw response: {xml_text[:200]}..."

def main():
    """Main function with error handling"""
    try:
        root = tk.Tk()
        app = ThermostatControlGUI(root)
        root.mainloop()
    except Exception as e:
        print(f"Error: {e}")
        input("Press Enter to close...")

if __name__ == "__main__":
    main()
