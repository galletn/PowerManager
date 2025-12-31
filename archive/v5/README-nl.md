# Power Manager v5.1 - Node-RED Flow voor Home Assistant

## 🎯 Overzicht

Intelligente energiebeheerder die automatisch apparaten aanstuurt op basis van:
- **Seizoen** (zomer = koeling, winter = verwarming)
- **Tarief** (piek/dal/superdal)
- **Export detectie** (koeling alleen als we energie terugleveren)
- **EV detectie** (auto aangesloten of niet)
- **Manual overrides** (gezin kan zelf kiezen)

## 📦 Bestanden

| Bestand | Beschrijving |
|---------|--------------|
| `power-manager-v5.json` | Complete flow - importeer dit in Node-RED |
| `power-manager-helpers.yaml` | HA helpers - voeg toe aan configuration.yaml |
| `power-manager-dashboard.yaml` | Lovelace cards voor dashboard |

## ⚡ Apparaten

### Aangestuurd door PM

| Apparaat | Entity | Vermogen | Seizoen |
|----------|--------|----------|---------|
| EV Charger | `switch.abb_terra_ac_charging` | 4-11 kW | Altijd |
| Boiler | `switch.storage_boiler` | 2.5 kW | Altijd |
| Pool HVAC | `climate.98d8639f920c` | 2 kW | Zomer |
| AC Living | `climate.living` | 1.5 kW | Beide |
| AC Mancave | `climate.mancave` | 1 kW | Beide |
| AC Bureau | `climate.bureau` | 1 kW | Zomer |
| AC Slaapkamer | `climate.slaapkamer` | 1 kW | Zomer |
| Heater Table | `switch.livingroom_table_heater_state` | 4.1 kW | Winter |
| Heater Right | `switch.livingroom_right_heater` | 2.5 kW | Winter |

### Sensoren

| Sensor | Beschrijving |
|--------|--------------|
| `sensor.electricity_meter_power_consumption` | P1 meter (kW) |
| `sensor.solaredge_i1_ac_power` | PV productie (W) |
| `sensor.abb_terra_ac_charging_state` | EV state code |
| `sensor.storage_boiler_power` | Boiler verbruik |
| `sensor.pool_heating_current_consumption` | Pool verbruik |
| `sensor.living_current_power` | AC living/mancave verbruik |
| `sensor.bureau_current_power` | AC bureau/slaapkamer verbruik |
| `sensor.livingroom_temperature_temperature` | Temp living |
| `sensor.bedroom_temperature_temperature` | Temp slaapkamer |
| `sensor.mancave_inside_temperature` | Temp mancave |

## 📊 Tariefstructuur

| Uur | Weekdag | Weekend | Max Import |
|-----|---------|---------|------------|
| 01:00-07:00 | **SUPERDAL** | **SUPERDAL** | 8 kW |
| 07:00-11:00 | PIEK | dal | 2.5 kW / 5 kW |
| 11:00-17:00 | dal | **SUPERDAL** | 5 kW / 8 kW |
| 17:00-22:00 | PIEK | dal | 2.5 kW / 5 kW |
| 22:00-01:00 | dal | dal | 5 kW |

## 🔄 Seizoenslogica

### ❄️ Winter (`pool_season` = off)

**Prioriteiten:**
1. 🔌 EV laden (als aangesloten)
2. 🔥 Boiler (deadline 06:30, alleen superdal)
3. 🔥 AC Living verwarmen (21°C)
4. 🔥 AC Mancave verwarmen (17°C)
5. 🔥 Heater Table (hogere prio zonder EV)
6. 🔥 Heater Right

**Regels:**
- Heaters NOOIT tijdens piek tarief
- AC kan load shed worden bij piek als overbelast
- Boiler urgent tussen 00:00-06:30 in superdal

### ☀️ Zomer (`pool_season` = on)

**Prioriteiten:**
1. 🏊 Pool verwarmen (low fan mode)
2. 🔥 Boiler
3. 🔌 EV laden
4. ❄️ Koeling (ALLEEN bij export!)

**Koeling volgorde:** Living → Slaapkamer → Bureau → Mancave

**Regels:**
- Koeling start alleen als `p1 < 0` (we exporteren)
- Koeling stopt zodra we niet meer exporteren
- Temp threshold: 25°C → koelen naar 22°C

## 🔌 EV State Codes

| Code | Status | PM Actie |
|------|--------|----------|
| 128 | Geen auto | Skip EV, heaters hogere prio |
| 129 | Klaar om te laden | Kan starten als vermogen beschikbaar |
| 130 | Vol | Niets doen |
| 132 | Aan het laden | Kan moduleren of pauzeren |

## 🎮 Manual Overrides

Via `input_select` helpers kan het gezin handmatig kiezen:

| Override | Opties |
|----------|--------|
| AC Living | 🤖 Auto / ❄️ Koelen / 🔥 Verwarmen / ⏹️ Uit |
| AC Slaapkamer | 🤖 Auto / ❄️ Koelen / 🔥 Verwarmen / ⏹️ Uit |
| AC Bureau | 🤖 Auto / ❄️ Koelen / 🔥 Verwarmen / ⏹️ Uit |
| AC Mancave | 🤖 Auto / ❄️ Koelen / 🔥 Verwarmen / ⏹️ Uit |
| Pool | 🤖 Auto / 🔥 Verwarmen / ⏹️ Uit |
| Boiler | 🤖 Auto / 🔥 Aan / ⏹️ Uit |
| EV | 🤖 Auto / ⚡ Laden / ⏹️ Uit |

**Gedrag:**
- **Auto**: PM beslist op basis van vermogen/tarief/seizoen
- **Anders**: PM respecteert de keuze en raakt het apparaat niet aan

## 📥 Installatie

### Stap 1: HA Helpers aanmaken

Voeg de inhoud van `power-manager-helpers.yaml` toe aan je `configuration.yaml`:

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
      - "🤖 Auto"
      - "❄️ Koelen"
      - "🔥 Verwarmen"
      - "⏹️ Uit"
    initial: "🤖 Auto"
    icon: mdi:air-conditioner
  # ... etc (zie helpers.yaml voor alle overrides)
```

Herstart Home Assistant na deze wijziging.

### Stap 2: Node-RED Flow importeren

1. Open Node-RED
2. Menu → Import (Ctrl+I)
3. Selecteer `power-manager-v5.json`
4. Klik Import
5. **Server is al geconfigureerd** (ID: `7a1ecefa.85d54`)
6. Deploy

### Stap 3: Dashboard (optioneel)

Kopieer de gewenste cards uit `power-manager-dashboard.yaml` naar je Lovelace dashboard.

## 📋 Plan Output Voorbeelden

### Winter - Piek tarief
```
🟡 PIEK | 1.6kW net | ☀️0W | 861W vrij
❄️ Winter | 🔌 Geen auto
🔥 Boiler: Vol ✓
🔥 AC Living: Verwarmt (21.2°C)
🔥 AC Mancave: Verwarmt (18.0°C)
🔥 Heater T: Wacht op dal (22:00)
🔥 Heater R: Wacht op dal (22:00)
✅ 861W beschikbaar
```

### Winter - Superdal met EV
```
🟢 SUPERDAL | -1.2kW net | ☀️0W | 9.2kW vrij
❄️ Winter | 🔌 Laden
🔌 EV: Laden @ 12A
🔥 Boiler: Verwarmt
🔥 AC Living: Verwarmt (20.5°C)
🔥 Heater T: Aanzetten
✅ 1.8kW beschikbaar
```

### Zomer - Export
```
🟢 DAL | -2.5kW net | ☀️4.2kW | 7.5kW vrij
☀️ Zomer | 🔌 Geen auto
🏊 Pool: Verwarmt
🔥 Boiler: Vol ✓
❄️ Living: Koelen (26.2°C)
❄️ Slaapkamer: Wacht (24.1°C < 25°C)
✅ 3.5kW beschikbaar
```

### Zomer - Geen export
```
🟡 DAL | 500W net | ☀️1.8kW | 4.5kW vrij
☀️ Zomer | 🔌 Geen auto
🏊 Pool: Verwarmt
🔥 Boiler: Wacht op 2.5kW
❄️ Koeling: Wacht op export
✅ 2.5kW beschikbaar
```

## 🔧 Configuratie aanpassen

Open de **⚙️ CONFIG** node in Node-RED om aan te passen:

```javascript
{
    // Grid limieten
    maxImportPeak: 2500,
    maxImportDal: 5000,
    maxImportSuperdal: 8000,
    
    // Timing (seconden)
    hysteresis: 300,      // Buffer voordat geschakeld wordt
    minOnTime: 300,       // Minimum aan-tijd
    minOffTime: 180,      // Minimum uit-tijd
    
    // EV
    evMinAmps: 6,
    evMaxAmps: 16,
    evWattsPerAmp: 692,
    
    // Boiler
    boilerPower: 2500,
    boilerIdleThreshold: 50,  // Onder dit = vol
    boilerDeadlineWinter: 6.5, // 06:30
    
    // Pool
    poolActivePower: 2000,
    
    // Heaters
    heaterTablePower: 4100,
    heaterRightPower: 2500,
    
    // AC units
    acLivingPower: 1500,
    acMancavePower: 1000,
    acBureauPower: 1000,
    acSlaapkamerPower: 1000,
    
    // Temperatuur
    winterSetpointLiving: 21,
    winterSetpointMancave: 17,
    summerCoolThreshold: 25,
    summerTargetTemp: 22
}
```

## 🔌 Pool HVAC

De pool warmtepomp (`climate.98d8639f920c`) wordt aangestuurd met:
- **Mode**: `heat` of `off`
- **Fan**: Altijd `low` (eco mode, minder lawaai)

## 🔥 Existing Helpers

Deze helpers moeten al bestaan (uit eerdere versies):
- `input_boolean.force_heat_boiler` - Force boiler aan
- `input_boolean.pool_season` - Zomer = on, Winter = off

## ⚠️ Troubleshooting

### Flow doet niets
- Check of HA server connected is (groene stip bij nodes)
- Kijk in Node-RED debug panel
- Controleer of alle entities bestaan in HA

### Te veel schakelen
- Verhoog `hysteresis` (bijv. 500W)
- Verhoog `minOnTime` en `minOffTime`

### Koeling start niet
- Check of `pool_season` = on
- Check of je daadwerkelijk exporteert (p1 < 0)
- Check of temp > 25°C

### Heaters starten niet
- Check of het geen piek tarief is
- Check of er genoeg vermogen beschikbaar is
- Heater Table heeft 4.1kW nodig!

### Override werkt niet
- Check of `input_select.pm_override_*` entities bestaan
- Check spelling inclusief emoji's

### Override entity bestaat niet
Als de override entity niet bestaat, krijg je een error. Maak ze aan via:
- Settings → Devices → Helpers → Create Helper → Dropdown
- Of via configuration.yaml (zie helpers.yaml)

## 📱 Notificaties

De flow stuurt `persistent_notification` bij elke actie. Zie de **📱 Notify** node om dit aan te passen naar:
- Mobile app notificaties
- Telegram
- Pushover

## 🗂️ Versiegeschiedenis

| Versie | Datum | Wijzigingen |
|--------|-------|-------------|
| v5.1 | 31 Dec 2024 | Vooruitkijkend plan, heaters altijd zichtbaar met timing |
| v5.0 | 31 Dec 2024 | Overrides, pool fan low, seizoenslogica, 4 AC units |
| v4.0 | 30 Dec 2024 | 3-tier logging (status/plan/actions) |
| v3.0 | 30 Dec 2024 | api-call-service nodes, fix deprecated ha-entity |

## 📁 Oude bestanden (kunnen verwijderd worden)

Deze bestanden zijn vervangen door v5:
- `power-manager-flow.json`
- `power-manager-flow-v2.json`
- `power-manager-v3-final.json`
- `power-manager-v4.json`
- `power-dashboard-flow.json`
- `power-connector-flow.json`
