# Cookie Import Tools for StreamCapEvo

This directory contains tools to import browser-exported cookies into the StreamCapEvo application.

## 📋 Overview

StreamCapEvo requires TikTok cookies to function properly. These tools help you:
- Convert browser-exported JSON cookies to the application's format
- Automatically backup existing configurations
- Validate cookie formats before import
- Provide multiple import methods for different use cases

## 🛠️ Available Tools

### 1. Simple Import Script (`import_cookies.py`)
- **Best for**: Quick, one-time imports
- **Features**: Basic cookie conversion and import
- **Usage**: `python import_cookies.py`

### 2. Advanced Import Script (`scripts/cookie_importer.py`)
- **Best for**: Regular use and advanced features
- **Features**: 
  - Interactive mode with guided prompts
  - Command-line interface with options
  - Comprehensive validation and error handling
  - Detailed logging and progress reporting
- **Usage**: See detailed usage section below

### 3. Batch Script (`import_cookies.bat`)
- **Best for**: Windows users who prefer GUI
- **Features**: Automatically detects and runs the best available script
- **Usage**: Double-click the file or run from command prompt

## 📤 Exporting Cookies from Browser

### Chrome/Edge (using browser extension)
1. Install a cookie export extension like "EditThisCookie" or "Cookie-Editor"
2. Navigate to `www.tiktok.com`
3. Use the extension to export cookies as JSON
4. Save the file (recommended location: `C:\\Users\\Test\\Videos\\Disco\\R\\www.tiktok.com.cookies.json`)

### Firefox (using browser extension)
1. Install "Cookie Quick Manager" extension
2. Navigate to `www.tiktok.com`
3. Open the extension and export cookies for the domain
4. Save as JSON format

### Manual Method (Developer Tools)
1. Open Developer Tools (F12)
2. Go to Application/Storage tab
3. Select Cookies → https://www.tiktok.com
4. Copy relevant cookies manually

## 🚀 Quick Start

### Method 1: Batch File (Easiest)
1. Double-click `import_cookies.bat`
2. Follow the prompts

### Method 2: Advanced Interactive Mode
```cmd
python scripts/cookie_importer.py
```

### Method 3: Command Line
```cmd
python scripts/cookie_importer.py --source "path/to/cookies.json" --target "config/cookies.json"
```

### Method 4: Quick Import with Defaults
```cmd
python scripts/cookie_importer.py --quick
```

## 📁 File Locations

### Default Source Location
```
C:\\Users\\Test\\Videos\\Disco\\R\\www.tiktok.com.cookies.json
```

### Target Location (Application Config)
```
E:\\dev\\StreamCapEvo\\config\\cookies.json
```

### Backup Location
Backups are automatically created with timestamp:
```
E:\\dev\\StreamCapEvo\\config\\cookies.json.backup_20250826_195012
```

## 🔧 Advanced Usage

### Command Line Options
```bash
# Interactive mode (default)
python scripts/cookie_importer.py

# Quick import with defaults
python scripts/cookie_importer.py --quick

# Custom source and target
python scripts/cookie_importer.py --source "my_cookies.json" --target "app_config.json"

# Quiet mode (minimal output)
python scripts/cookie_importer.py --quiet --quick

# Show help
python scripts/cookie_importer.py --help

# Show version
python scripts/cookie_importer.py --version
```

### Expected Cookie Format
The import scripts expect a JSON array of cookie objects:
```json
[
  {
    "name": "sessionid",
    "value": "abc123def456",
    "domain": ".tiktok.com",
    "path": "/",
    "expires": 1769209789.93664,
    "httpOnly": true,
    "secure": true
  },
  {
    "name": "uid_tt",
    "value": "xyz789uvw012",
    "domain": ".tiktok.com",
    "path": "/",
    "expires": 1769209789.93647,
    "httpOnly": true,
    "secure": true
  }
]
```

## 🔍 Troubleshooting

### Common Issues

#### "File not found" Error
- Check that the cookie export file exists at the specified path
- Ensure the path doesn't contain special characters
- Use absolute paths when in doubt

#### "Invalid JSON format" Error
- Verify the exported file is valid JSON
- Check that cookies were exported in the correct format (array of objects)
- Try exporting cookies again from the browser

#### "No valid cookies found" Error
- Ensure cookies contain both 'name' and 'value' fields
- Check that you're logged into TikTok in the browser before exporting
- Verify you exported cookies from the correct domain (www.tiktok.com)

#### Permission Denied Error
- Run the command prompt/terminal as administrator
- Check that the target directory is writable
- Ensure the application config file isn't currently in use

### Validation Steps
After importing cookies, verify the import was successful:

1. Check that `config/cookies.json` was updated
2. Look for the backup file with timestamp
3. Verify the TikTok cookie string is present in the config
4. Test the application functionality

## 🔒 Security Notes

- Cookie files contain sensitive authentication data
- Store exported cookie files securely
- Delete exported cookie files after importing
- Backups are created automatically but should be cleaned up periodically
- Never share cookie files or commit them to version control

## 🆘 Support

If you encounter issues:

1. Check the troubleshooting section above
2. Verify Python is installed and accessible
3. Ensure you have write permissions to the target directory
4. Try using the interactive mode for guided assistance
5. Check that your exported cookies are in the correct format

## 📝 Script Details

### File Structure
```
StreamCapEvo/
├── import_cookies.py              # Simple import script
├── import_cookies.bat            # Windows batch wrapper
├── COOKIE_IMPORT_README.md       # This documentation
├── scripts/
│   └── cookie_importer.py        # Advanced import script
└── config/
    ├── cookies.json              # Target configuration
    └── cookies.json.backup_*     # Automatic backups
```

### What Gets Updated
The import process updates the `tiktok` field in `config/cookies.json`:
```json
{
    "tiktok": "sessionid=abc123; uid_tt=xyz789; sid_tt=def456; ..."
}
```

---

**Last Updated**: August 26, 2025  
**Version**: 1.0.0
