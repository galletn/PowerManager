# Power Manager v6.0 - Node-RED Flow for Home Assistant

## Overview

Intelligent energy manager that automatically controls devices based on:
- **Season** (summer = cooling, winter = heating)
- **Tariff** (peak/off-peak/super-off-peak)
- **Export detection** (cooling only when exporting to grid)
- **EV detection** (car connected or not)
- **Manual overrides** (family can override any device)

## Files

| File | Description |
|------|-------------|
| `power-manager-v6.json` | Complete flow - import into Node-RED |
| `power-manager-helpers-en.yaml` | HA helpers - add to configuration.yaml |
| `power-manager-dashboard-en.yaml` | Lovelace cards for dashboard |

## Prerequisites

- Home Assistant with Node-RED add-on installed
- Node-RED Companion integration configured
- All device entities must exist in Home Assistant

## Controlled Devices

### Managed by Power Manager

| Device | Entity | Power | Season |
|--------|--------|-------|--------|
| EV Charger | `switch.abb_terra_ac_charging` | 4-11 kW | Both |
| Boiler | `switch.storage_boiler` | 2.5 kW | Both |
| Pool HVAC | `climate.98d8639f920c` | 2 kW | Summer |
| AC Living | `climate.living` | 1.5 kW | Both |
| AC Mancave | `climate.mancave` | 1 kW | Both |
| AC Office | `climate.bureau` | 1 kW | Summer |
| AC Bedroom | `climate.slaapkamer` | 1 kW | Summer |
| Heater Table | `switch.livingroom_table_heater_state` | 4.1 kW | Winter |
| Heater Right | `switch.livingroom_right_heater` | 2.5 kW | Winter |

### Sensors

| Sensor | Description |
|--------|-------------|
| `sensor.electricity_meter_power_consumption` | P1 meter (kW) |
| `sensor.solaredge_i1_ac_power` | PV production (W) |
| `sensor.abb_terra_ac_charging_state` | EV state code |
| `sensor.storage_boiler_power` | Boiler consumption |
| `sensor.pool_heating_current_consumption` | Pool consumption |
| `sensor.living_current_power` | AC living/mancave power |
| `sensor.bureau_current_power` | AC office/bedroom power |
| `sensor.livingroom_temperature_temperature` | Living room temperature |
| `sensor.bedroom_temperature_temperature` | Bedroom temperature |
| `sensor.mancave_inside_temperature` | Mancave temperature |

## Tariff Structure

| Time | Weekday | Weekend | Max Import |
|------|---------|---------|------------|
| 01:00-07:00 | **SUPER OFF-PEAK** | **SUPER OFF-PEAK** | 8 kW |
| 07:00-11:00 | PEAK | off-peak | 2.5 kW / 5 kW |
| 11:00-17:00 | off-peak | **SUPER OFF-PEAK** | 5 kW / 8 kW |
| 17:00-22:00 | PEAK | off-peak | 2.5 kW / 5 kW |
| 22:00-01:00 | off-peak | off-peak | 5 kW |

## Seasonal Logic

### Winter Mode (`pool_season` = off)

**Priority order:**
1. EV charging (if connected)
2. Boiler (deadline 06:30, super off-peak only)
3. AC Living heating (21C)
4. AC Mancave heating (17C)
5. Heater Table (higher priority without EV)
6. Heater Right

**Rules:**
- Heaters NEVER during peak tariff
- AC can be load-shed during peak if overloaded
- Boiler urgent between 00:00-06:30 during super off-peak

### Summer Mode (`pool_season` = on)

**Priority order:**
1. Pool heating (low fan mode)
2. Boiler
3. EV charging
4. Cooling (ONLY when exporting!)

**Cooling order:** Living > Bedroom > Office > Mancave

**Rules:**
- Cooling starts only when `p1 < 0` (exporting to grid)
- Cooling stops when no longer exporting
- Temperature threshold: 25C starts cooling to 22C

## EV State Codes

| Code | Status | PM Action |
|------|--------|-----------|
| 128 | No car | Skip EV, heaters get higher priority |
| 129 | Ready to charge | Can start if power available |
| 130 | Full | No action |
| 132 | Charging | Can modulate or pause |

## Manual Overrides

Using `input_select` helpers, family members can manually override:

| Override | Options |
|----------|---------|
| AC Living | Auto / Cool / Heat / Off |
| AC Bedroom | Auto / Cool / Heat / Off |
| AC Office | Auto / Cool / Heat / Off |
| AC Mancave | Auto / Cool / Heat / Off |
| Pool | Auto / Heat / Off |
| Boiler | Auto / On / Off |
| EV | Auto / Charge / Off |

**Behavior:**
- **Auto**: PM decides based on power/tariff/season
- **Other**: PM respects the choice and doesn't touch the device

## Installation

### Step 1: Create HA Helpers

Add the contents of `power-manager-helpers-en.yaml` to your `configuration.yaml`:

```yaml
# In configuration.yaml
input_text:
  power_manager_status:
    name: Power Manager Status
    max: 255
  power_manager_plan:
    name: Power Manager Plan
    max: 255
  power_manager_actions:
    name: Power Manager Actions
    max: 255

input_select:
  pm_override_ac_living:
    name: AC Living
    options:
      - "Auto"
      - "Cool"
      - "Heat"
      - "Off"
    initial: "Auto"
    icon: mdi:air-conditioner
  # ... see helpers.yaml for all overrides
```

Restart Home Assistant after making changes.

### Step 2: Import Node-RED Flow

1. Open Node-RED
2. Menu > Import (Ctrl+I)
3. Select `power-manager-v6.json`
4. Click Import
5. **Server is pre-configured** (ID: `7a1ecefa.85d54`)
6. Deploy

### Step 3: Dashboard (optional)

Copy the cards from `power-manager-dashboard-en.yaml` to your Lovelace dashboard.

## Plan Output Examples

### Winter - Peak Tariff
```
PEAK | Grid: 1.6kW | PV: 0W | Avail: 861W
Winter | EV: No car
Boiler: Full
AC Living: Heating (21.2C)
AC Mancave: Heating (18.0C)
Heater Table: Waiting for off-peak (22:00)
Heater Right: Waiting for off-peak (22:00)
Available: 861W
```

### Winter - Super Off-Peak with EV
```
SUPER OFF-PEAK | Grid: -1.2kW | PV: 0W | Avail: 9.2kW
Winter | EV: Charging
EV: Charging @ 12A
Boiler: Heating
AC Living: Heating (20.5C)
Heater Table: Starting
Available: 1.8kW
```

### Summer - Exporting
```
OFF-PEAK (exp) | Grid: -2.5kW | PV: 4.2kW | Avail: 7.5kW
Summer | EV: No car
Pool: Heating
Boiler: Full
AC Living: Cooling (26.2C)
AC Bedroom: Waiting (24.1C < 25C)
Available: 3.5kW
```

### Summer - Not Exporting
```
OFF-PEAK | Grid: 500W | PV: 1.8kW | Avail: 4.5kW
Summer | EV: No car
Pool: Heating
Boiler: Waiting for 2.5kW
Cooling: Waiting for export
Available: 2.5kW
```

## Configuration

Open the **CONFIG** node in Node-RED to customize settings:

```javascript
{
    // Grid limits
    maxImport: {
        peak: 2500,
        offPeak: 5000,
        superOffPeak: 8000
    },

    // Timing (seconds)
    hysteresis: 300,        // Buffer before switching
    minOnTime: 300,         // Minimum on-time
    minOffTime: 180,        // Minimum off-time
    evAmpChangeThreshold: 2, // Prevent EV amp flapping

    // EV
    ev: {
        minAmps: 6,
        maxAmps: 16,
        wattsPerAmp: 692
    },

    // Boiler
    boiler: {
        power: 2500,
        idleThreshold: 50,      // Below = fully heated
        deadlineWinter: 6.5     // 06:30
    },

    // Pool
    pool: {
        activePower: 2000
    },

    // Heaters
    heaters: {
        table: { power: 4100 },
        right: { power: 2500 }
    },

    // AC units
    ac: {
        living:  { power: 1500, winterSetpoint: 21 },
        mancave: { power: 1000, winterSetpoint: 17 },
        office:  { power: 1000, winterSetpoint: 22 },
        bedroom: { power: 1000, winterSetpoint: 22 }
    },

    // Temperature
    summerCoolThreshold: 25,
    summerTargetTemp: 22
}
```

## Pool HVAC

The pool heat pump (`climate.98d8639f920c`) is controlled with:
- **Mode**: `heat` or `off`
- **Fan**: Always `low` (eco mode, less noise)

## Existing Helpers

These helpers must already exist (from previous versions):
- `input_boolean.force_heat_boiler` - Force boiler on
- `input_boolean.pool_season` - Summer = on, Winter = off

## Troubleshooting

### Flow does nothing
- Check if HA server is connected (green dot on nodes)
- Check Node-RED debug panel for errors
- Verify all entities exist in HA

### Too much switching
- Increase `hysteresis` (e.g., 500W)
- Increase `minOnTime` and `minOffTime`
- Check `evAmpChangeThreshold` for EV

### Cooling doesn't start
- Check if `pool_season` = on
- Check if actually exporting (p1 < 0)
- Check if temperature > 25C

### Heaters don't start
- Check if not peak tariff
- Check if enough power available
- Heater Table needs 4.1kW!

### Override doesn't work
- Check if `input_select.pm_override_*` entities exist
- Check spelling (case-sensitive)
- Verify override values match expected options

### Override entity doesn't exist
If the override entity doesn't exist, you'll get an error. Create them via:
- Settings > Devices > Helpers > Create Helper > Dropdown
- Or via configuration.yaml (see helpers.yaml)

## Notifications

The flow sends `persistent_notification` on each action. Modify the **Notify** node to change to:
- Mobile app notifications
- Telegram
- Pushover

## Version History

| Version | Date | Changes |
|---------|------|---------|
| v6.0 | 31 Dec 2024 | English translation, input validation, mutex, EV amp threshold |
| v5.1 | 31 Dec 2024 | Forward-looking plan, heaters always visible with timing |
| v5.0 | 31 Dec 2024 | Overrides, pool fan low, seasonal logic, 4 AC units |
| v4.0 | 30 Dec 2024 | 3-tier logging (status/plan/actions) |
| v3.0 | 30 Dec 2024 | api-call-service nodes, fix deprecated ha-entity |

## Migration from v5.1

1. Import `power-manager-v6.json` (creates new tab)
2. Update helpers to English options (see `power-manager-helpers-en.yaml`)
3. Update dashboard cards to use English labels
4. Delete old Power Manager tab
5. Deploy

## FAQ

**Q: Can I keep Dutch labels in the dashboard?**
A: Yes, edit the `input_select` options in `helpers-en.yaml` back to Dutch. The flow understands both languages.

**Q: Why is my EV charging amperage jumping around?**
A: Increase `evAmpChangeThreshold` in CONFIG node (default: 2A).

**Q: How do I add a new AC unit?**
A: Add entity to `config.entities.ac`, add state gathering node, add output handler, and include in decision logic.

**Q: The flow runs but doesn't control devices?**
A: Check the debug node output. Verify entities exist and are controllable. Check HA logs for service call errors.
