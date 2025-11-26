# Panasonic WIFAN - Home Assistant Integration

A native Home Assistant integration for Panasonic Malaysia WiFi fans. This integration communicates directly with their Ceiling Fan cloud API.

## Features
- Auto-discover fans
- Turn on/off
- Set fan speed (1-10 range)
- Reverse mode
- Yuragi mode (implemented as "oscillation")
- Optimistic state updates (polling every 5 minutes)

## Installation

### HACS (Recommended)
1. Open HACS in Home Assistant
2. Go to Integrations
3. Click the three dots in the top right corner
4. Select "Custom repositories"
5. Add this repository URL: `https://github.com/doubleukay/panasonic-wifan-ha`
6. Select category: "Integration"
7. Click "Add"
8. Search for "Panasonic WIFAN" and install

### Manual Installation
1. Copy the `custom_components/panasonic_wifan` directory to your Home Assistant's `custom_components` directory
2. Restart Home Assistant

## Configuration
1. Go to Settings → Devices & Services
2. Click "+ Add Integration"
3. Search for "Panasonic WIFAN"
4. Enter your Panasonic username (email) and password. NOTE: social login is not supported.
5. Click Submit

Your fans will be automatically discovered and added as devices.

## Support

For issues and feature requests, please use the [GitHub issue tracker](https://github.com/doubleukay/panasonic-wifan-ha/issues).

## License

Copyright 2025 Woon Wai Keen

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.