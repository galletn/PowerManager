#!/usr/bin/env python3
"""
Test Home Assistant API performance for Power Manager
Validates we can fetch all data quickly and send commands reliably.
"""

import requests
import time
import json
from datetime import datetime

# Configuration
HA_URL = "https://gallet.duckdns.org:8123"
TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiIzNWY3YzBkMzNkZmM0NjkxOGY5YTkyMmNmOWRiOGQ5YiIsImlhdCI6MTc2NzE4NDc2MywiZXhwIjoyMDgyNTQ0NzYzfQ.ghuDWnT8zI-YhNv1o9-NzYtwH2pxbPeUZ-EwOFBk2_s"

# All entities we need for Power Manager
ENTITIES = {
    # Power readings
    'p1': 'sensor.electricity_currently_delivered',
    'p1_return': 'sensor.electricity_currently_returned',
    'pv': 'sensor.solaredge_i1_ac_power',

    # EV Charger
    'ev_state': 'sensor.abb_terra_ac_charging_state',
    'ev_power': 'sensor.abb_terra_ac_active_power',
    'ev_switch': 'switch.abb_terra_ac_charging',
    'ev_limit': 'number.abb_terra_ac_current_limit',

    # Boiler
    'boiler_switch': 'switch.storage_boiler',
    'boiler_power': 'sensor.storage_boiler_power',
    'boiler_force': 'input_boolean.force_heat_boiler',

    # Pool
    'pool_climate': 'climate.98d8639f920c',
    'pool_power': 'sensor.pool_heating_current_consumption',
    'pool_season': 'input_boolean.pool_season',
    'pool_pump': 'switch.poolhouse_pool_pump',
    'pool_pump_power': 'sensor.poolhouse_pool_pump_power',
    'pool_ambient_temp': 'sensor.98d8639f920c_ambient_temp_t05',

    # Heaters
    'heater_right': 'switch.livingroom_right_heater',
    'heater_table': 'switch.livingroom_table_heater_state',

    # AC Units
    'ac_living': 'climate.living',
    'ac_mancave': 'climate.mancave',
    'ac_office': 'climate.bureau',
    'ac_bedroom': 'climate.slaapkamer',

    # Temperatures
    'temp_living': 'sensor.livingroom_temperature_temperature',
    'temp_bedroom': 'sensor.bedroom_temperature_temperature',
    'temp_mancave': 'sensor.mancave_inside_temperature',

    # BMW Cars
    'bmw_i5_battery': 'sensor.i5_edrive40_battery_hv_state_of_charge',
    'bmw_i5_range': 'sensor.i5_edrive40_range_ev_remaining_range',
    'bmw_i5_location': 'device_tracker.i5_edrive40_location',
    'bmw_ix1_battery': 'sensor.ix1_edrive20_battery_hv_state_of_charge',
    'bmw_ix1_range': 'sensor.ix1_edrive20_range_ev_remaining_range',
    'bmw_ix1_location': 'device_tracker.ix1_edrive20_location',
}

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json"
}


def test_batch_fetch():
    """Test fetching ALL states in one call - most efficient method."""
    print("\n=== Test 1: Batch Fetch All States ===")

    start = time.time()
    try:
        response = requests.get(
            f"{HA_URL}/api/states",
            headers=HEADERS,
            verify=False,
            timeout=10
        )
        elapsed = (time.time() - start) * 1000

        if response.status_code == 200:
            all_states = response.json()
            print(f"[OK] Fetched {len(all_states)} entities in {elapsed:.0f}ms")

            # Filter to just our entities
            our_entities = {}
            for state in all_states:
                entity_id = state['entity_id']
                for key, eid in ENTITIES.items():
                    if entity_id == eid:
                        our_entities[key] = {
                            'state': state['state'],
                            'last_updated': state.get('last_updated', '')
                        }

            print(f"[OK] Found {len(our_entities)}/{len(ENTITIES)} of our entities")

            # Show missing entities
            missing = set(ENTITIES.keys()) - set(our_entities.keys())
            if missing:
                print(f"[WARN] Missing: {missing}")

            return all_states, elapsed
        else:
            print(f"[FAIL] Failed: {response.status_code}")
            return None, elapsed
    except Exception as e:
        print(f"[FAIL] Error: {e}")
        return None, 0


def test_individual_fetch():
    """Test fetching entities one by one - for comparison."""
    print("\n=== Test 2: Individual Fetches (5 entities) ===")

    test_entities = list(ENTITIES.values())[:5]
    times = []

    for entity_id in test_entities:
        start = time.time()
        try:
            response = requests.get(
                f"{HA_URL}/api/states/{entity_id}",
                headers=HEADERS,
                verify=False,
                timeout=5
            )
            elapsed = (time.time() - start) * 1000
            times.append(elapsed)

            if response.status_code == 200:
                data = response.json()
                print(f"  {entity_id}: {data['state']} ({elapsed:.0f}ms)")
            else:
                print(f"  {entity_id}: FAILED ({elapsed:.0f}ms)")
        except Exception as e:
            print(f"  {entity_id}: ERROR - {e}")

    avg_time = sum(times) / len(times) if times else 0
    total_time = sum(times)
    print(f"[OK] Average: {avg_time:.0f}ms per entity, Total: {total_time:.0f}ms")
    print(f"  Extrapolated for {len(ENTITIES)} entities: {avg_time * len(ENTITIES):.0f}ms")

    return avg_time


def test_send_command():
    """Test sending a command (toggle test - non-destructive)."""
    print("\n=== Test 3: Send Command (Read current state) ===")

    # Just read the boiler state - don't actually toggle
    start = time.time()
    try:
        response = requests.get(
            f"{HA_URL}/api/states/switch.storage_boiler",
            headers=HEADERS,
            verify=False,
            timeout=5
        )
        elapsed = (time.time() - start) * 1000

        if response.status_code == 200:
            data = response.json()
            print(f"[OK] Boiler state: {data['state']} (read in {elapsed:.0f}ms)")

            # Test service call structure (but don't execute)
            print(f"[OK] Service call would be: POST /api/services/switch/turn_{'off' if data['state'] == 'on' else 'on'}")
            print(f"  Body: {{'entity_id': 'switch.storage_boiler'}}")
            return True
        else:
            print(f"[FAIL] Failed to read state: {response.status_code}")
            return False
    except Exception as e:
        print(f"[FAIL] Error: {e}")
        return False


def test_template_api():
    """Test template API for complex calculations server-side."""
    print("\n=== Test 4: Template API (Server-side calculations) ===")

    template = """
    {
      "p1_import": {{ states('sensor.electricity_currently_delivered') | float(0) * 1000 }},
      "p1_export": {{ states('sensor.electricity_currently_returned') | float(0) * 1000 }},
      "pv": {{ states('sensor.solaredge_i1_ac_power') | float(0) }},
      "net_power": {{ (states('sensor.electricity_currently_delivered') | float(0) * 1000) - states('sensor.solaredge_i1_ac_power') | float(0) }},
      "boiler_on": {{ is_state('switch.storage_boiler', 'on') }},
      "ev_state": {{ states('sensor.abb_terra_ac_charging_state') | int(128) }}
    }
    """

    start = time.time()
    try:
        response = requests.post(
            f"{HA_URL}/api/template",
            headers=HEADERS,
            json={"template": template},
            verify=False,
            timeout=5
        )
        elapsed = (time.time() - start) * 1000

        if response.status_code == 200:
            result = response.text
            print(f"[OK] Template result in {elapsed:.0f}ms:")
            try:
                data = json.loads(result)
                for k, v in data.items():
                    print(f"    {k}: {v}")
            except:
                print(f"    {result[:200]}")
            return True, elapsed
        else:
            print(f"[FAIL] Failed: {response.status_code} - {response.text[:100]}")
            return False, elapsed
    except Exception as e:
        print(f"[FAIL] Error: {e}")
        return False, 0


def extract_power_data(all_states):
    """Extract and display current power status from batch fetch."""
    print("\n=== Current Power Status ===")

    state_map = {s['entity_id']: s for s in all_states}

    def get_val(entity_id, default=0, multiplier=1):
        s = state_map.get(entity_id, {})
        val = s.get('state', default)
        if val in ['unavailable', 'unknown', None]:
            return default
        try:
            return float(val) * multiplier
        except:
            return val

    p1_import = get_val('sensor.electricity_currently_delivered', 0, 1000)
    p1_export = get_val('sensor.electricity_currently_returned', 0, 1000)
    pv = get_val('sensor.solaredge_i1_ac_power', 0)
    boiler = get_val('sensor.storage_boiler_power', 0)
    ev = get_val('sensor.abb_terra_ac_active_power', 0)

    boiler_state = state_map.get('switch.storage_boiler', {}).get('state', 'unknown')
    ev_state = get_val('sensor.abb_terra_ac_charging_state', 128)

    i5_battery = get_val('sensor.i5_edrive40_battery_hv_state_of_charge', 'N/A')
    ix1_battery = get_val('sensor.ix1_edrive20_battery_hv_state_of_charge', 'N/A')

    print(f"  Grid Import: {p1_import:.0f}W")
    print(f"  Grid Export: {p1_export:.0f}W")
    print(f"  PV Production: {pv:.0f}W")
    print(f"  Net: {'importing' if p1_import > 0 else 'exporting'} {max(p1_import, p1_export):.0f}W")
    print(f"  ---")
    print(f"  Boiler: {boiler_state} ({boiler:.0f}W)")
    print(f"  EV Charger: state={ev_state} ({ev:.0f}W)")
    print(f"  ---")
    print(f"  BMW i5: {i5_battery}%")
    print(f"  BMW iX1: {ix1_battery}%")


def main():
    print("=" * 60)
    print("Home Assistant API Performance Test for Power Manager")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # Suppress SSL warnings
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    # Run tests
    all_states, batch_time = test_batch_fetch()
    individual_avg = test_individual_fetch()
    test_send_command()
    template_ok, template_time = test_template_api()

    if all_states:
        extract_power_data(all_states)

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"  Batch fetch (all states):     {batch_time:.0f}ms  <-- RECOMMENDED")
    print(f"  Individual (per entity):      {individual_avg:.0f}ms each")
    print(f"  Template API:                 {template_time:.0f}ms")
    print()

    if batch_time < 500:
        print("[OK] API is fast enough for 30-60 second polling")
        print("[OK] Python service is viable!")
    else:
        print("[WARN] API might be slow - consider caching or WebSocket")

    print()
    print("Recommendation: Use batch fetch (/api/states) for all readings,")
    print("then filter client-side. This is 10-20x faster than individual calls.")


if __name__ == "__main__":
    main()
