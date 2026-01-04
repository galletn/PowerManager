POWER MANAGER - HOME ASSISTANT STANDALONE DASHBOARD
====================================================

This folder contains files for hosting the dashboard in HA's www folder.
The dashboard.js and style.css are copies from dashboard/static/ - there
is only ONE source of truth for the dashboard code.

FILES TO DEPLOY:
----------------
From this folder:
- dashboard.html          - Full dashboard with API URL config
- dashboard-power.html    - Compact power flow view
- dashboard-timeline.html - Compact timeline/schedule view

From dashboard/static/:
- dashboard.js    - Main JavaScript (supports standalone mode)
- style.css       - Stylesheet

CONFIGURATION:
--------------
Edit ALL dashboard*.html files and set the API URL:

    window.POWER_MANAGER_API = 'https://192.168.68.78:8081';

DEPLOYMENT:
-----------
1. Copy files to HA's www folder:

   # On the HA server, create the folder:
   mkdir -p /config/www/power-manager

   # Copy files (from Power Manager source):
   cp ha-standalone/*.html /config/www/power-manager/
   cp dashboard/static/dashboard.js /config/www/power-manager/
   cp dashboard/static/style.css /config/www/power-manager/

2. Access at:
   - https://your-ha:8123/local/power-manager/dashboard.html
   - https://your-ha:8123/local/power-manager/dashboard-power.html
   - https://your-ha:8123/local/power-manager/dashboard-timeline.html

3. Or add as HA sidebar panel in configuration.yaml:

   panel_iframe:
     power_manager:
       title: "Power Manager"
       icon: mdi:flash
       url: "/local/power-manager/dashboard.html"

TROUBLESHOOTING:
----------------
If values don't load:

1. SSL Certificate Issue (most common)
   The browser may block requests to the Power Manager API because it uses
   a self-signed or untrusted certificate. To fix:

   - Open https://192.168.68.78:8081 directly in your browser
   - Accept the security warning / add exception
   - Then refresh the dashboard

2. Check browser console (F12 -> Console) for errors

3. Verify the API is running:
   curl -k https://192.168.68.78:8081/api/status

4. If using internal IP, make sure it's accessible from your network

MAINTENANCE:
------------
The dashboard.js now supports both modes automatically:
- When served by Power Manager: uses relative URLs
- When served standalone: uses window.POWER_MANAGER_API

So there's only ONE dashboard.js to maintain. When you update
dashboard/static/dashboard.js, just copy it to HA's www folder again.

SECURITY:
---------
- The Power Manager API has no authentication
- It's only accessible from your internal network
- External access requires Tailscale
- No secrets are exposed in the JavaScript
