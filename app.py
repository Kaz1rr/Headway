import csv
import time
import requests
from flask import Flask, render_template, request, jsonify, redirect, url_for, session
from flask_session import Session
from datetime import datetime

app = Flask(__name__, template_folder="templates")
app.secret_key = 'your-secret-key-here'
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Default settings
DEFAULT_SETTINGS = {
    'text_color': '#00ffff',
    'glow_strength': '15'
}

def get_line_name(stop_id):
    route_id = stop_id[0]
    base_url = f"https://demo.transiter.dev/systems/us-ny-subway/routes/{route_id}"

    try:
        response = requests.get(base_url)
        response.raise_for_status()
        route_data = response.json()
        train_name = route_data.get("shortName", "Unknown Train")
        
        # Special handling for shuttles
        if train_name == "S":
            if route_id == "GS":
                return "42nd Street Shuttle"
            elif route_id == "FS":
                return "Franklin Avenue Shuttle"
            elif route_id == "H":
                return "Rockaway Shuttle"
            else:
                return "Shuttle"
        return train_name
    except requests.exceptions.RequestException as e:
        print(f"Error fetching route info for {route_id}: {e}")
        return "Unknown Train"

def parse_stops(file_path, specific_line_stops=None):
    lines_stations = {}
    
    with open(file_path, newline='', encoding='utf-8') as file:
        reader = csv.DictReader(file)
        for row in reader:
            stop_id = row["stop_id"]
            stop_name = row["stop_name"]
            
            # Skip if it's a child station (ends with N or S)
            if stop_id[-1] in ['N', 'S']:
                continue
            
            # If specific stops are provided, only include those
            if specific_line_stops:
                for line, stops in specific_line_stops.items():
                    if stop_id in stops:
                        if stop_id not in lines_stations:
                            lines_stations[stop_id] = {
                                "stop_id": stop_id,
                                "stop_name": stop_name,
                                "stop_lat": float(row["stop_lat"]),
                                "stop_lon": float(row["stop_lon"])
                            }
            
    return lines_stations

def get_upcoming_trains_for_stop(stop_id, lines_stations):
    # For a given stop_id, we'll check both N and S directions
    stop_ids = [stop_id]
    
    if stop_id[-1] not in ['N', 'S']:
        stop_ids.extend([f"{stop_id}N", f"{stop_id}S"])

    all_train_info = []
    seen_trains = set()
    
    for current_stop_id in stop_ids:
        url = f"https://demo.transiter.dev/systems/us-ny-subway/stops/{current_stop_id}"
        try:
            response = requests.get(url)
            response.raise_for_status()
            data = response.json()
        except (requests.exceptions.RequestException, KeyError, IndexError) as e:
            print(f"Error fetching data for stop {current_stop_id}: {e}")
            continue

        now = time.time()
        upcoming_trains = [stop_time for stop_time in data.get("stopTimes", []) if int(stop_time["departure"].get("time", 0)) > now]

        for stop_time in upcoming_trains[:2]:  # Limit to the next 2 trains
            departure_time = stop_time.get("departure", {}).get("time", None)

            if departure_time is None:
                print(f"Skipping train info due to missing departure time for stop {current_stop_id}")
                continue

            seconds_to_leave = int(departure_time) - now
            minutes, _ = divmod(seconds_to_leave, 60)

            trip_info = stop_time.get("trip", {})
            route_id = trip_info.get("route", {}).get("id", "Unknown")
            route_name = get_line_name(route_id)
            destination = trip_info.get("destination", {}).get("name", "Unknown")
            headsign = stop_time.get("headsign", "Unknown")
            trip_id = trip_info.get("id", "Unknown")

            if destination == "Unknown":
                destination = "No destination available"
            if route_name == "Unknown Line":
                route_name = "No route available"

            train_details = f"to {destination} [{headsign}] leaves in {int(minutes)} min"

            if train_details not in seen_trains:
                seen_trains.add(train_details)
                train_info = {
                    "train_details": train_details,
                    "trip_id": trip_id,
                    "destination": destination,
                    "headsign": headsign,
                    "departure_time": departure_time,
                    "departure_in_minutes": int(minutes),
                    "route_name": route_name
                }
                all_train_info.append(train_info)
    
    return all_train_info

def get_stop_name(stop_id):
    url = f"https://demo.transiter.dev/systems/us-ny-subway/stops/{stop_id}"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        return data["name"]
    except requests.exceptions.RequestException as e:
        print(f"Error fetching station name for {stop_id}: {e}")
        return "Unknown Station"

def get_transfers_for_stop(stop_id):
    url = f"https://demo.transiter.dev/systems/us-ny-subway/stops/{stop_id}"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()

        transfers = data.get('transfers', [])
        processed_transfers = []
        for transfer in transfers:
            from_route = transfer['fromStop']['id'][0]
            to_route = transfer['toStop']['id'][0]
            
            # Handle special cases for shuttles
            if from_route in ['H', 'S', 'FS']:
                if from_route == 'H':
                    from_route = 'h'  # Rockaway
                elif from_route == 'FS':
                    from_route = 'fs'  # Franklin
                else:
                    from_route = 's'  # 42nd St
                    
            if to_route in ['H', 'S', 'FS']:
                if to_route == 'H':
                    to_route = 'h'  # Rockaway
                elif to_route == 'FS':
                    to_route = 'fs'  # Franklin
                else:
                    to_route = 's'  # 42nd St
            
            transfer_info = {
                'from_stop': transfer['fromStop']['name'],
                'to_stop': transfer['toStop']['name'],
                'from_route': from_route.lower(),
                'to_route': to_route.lower(),
                'from_stop_id': transfer['fromStop']['id'],
                'to_stop_id': transfer['toStop']['id']
            }
            processed_transfers.append(transfer_info)
        return processed_transfers
    except requests.exceptions.RequestException as e:
        print(f"Error fetching transfers for {stop_id}: {e}")
        return []

def get_route_for_stop(stop_id):
    url = f"https://demo.transiter.dev/systems/us-ny-subway/stops/{stop_id}"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        route_id = data.get("route", {}).get("id", "Unknown")
        return get_line_name(route_id)
    except requests.exceptions.RequestException as e:
        print(f"Error fetching route for {stop_id}: {e}")
        return "Unknown Route"

def get_headways_for_stop(stop_id):
    url = f"https://demo.transiter.dev/systems/us-ny-subway/stops/{stop_id}/realtime"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        
        headways = []
        if 'data' in data:
            for route in data['data']:
                route_id = route['route']['id']
                if 'headways' in route:
                    headway_info = {
                        'route_id': route_id,
                        'scheduled': route['headways'].get('scheduled'),
                        'observed': route['headways'].get('observed')
                    }
                    headways.append(headway_info)
        return headways
    except requests.exceptions.RequestException as e:
        print(f"Error fetching headways for {stop_id}: {e}")
        return []

@app.route('/')
def index():
    valid_lines = ['1', '2', '3', '4', '5', '6', '7', 'A', 'B', 'C', 'D', 'E', 'F', 'G', 'J', 'L', 'M', 'N', 'Q', 'R', 'S', 'T', "H", "W", "9", "FS", "GS", "SIR"]
    settings = session.get('settings', DEFAULT_SETTINGS)
    return render_template('index.html', services=valid_lines, settings=settings)

@app.route('/service/<line>')
def service(line):
    specific_line_stops = {
        # Main Lines
        '1': ['101', '103', '104', '106', '107', '108', '109', '110', '111', '112', '113', '114', '115', '116', '117', '118', '119', '120', '121', '122', '123', '124', '125', '126', '127', '128', '129', '130', '131', '132', '133', '134', '135', '136', '137', '138', '139', '140', '142'],
        '2': ['201', '202', '203', '204', '205', '206', '207', '208', '209', '210', '211', '212', '213', '214', '215', '216', '217', '218', '219', '220', '221', '222', '224', '225', '226', '227', '228', '229', '230', '231', '232', '233', '234', '235', '236', '237', '238', '239', '241', '242', '243', '244', '245', '246', '247', '248', '249', '250', '251'],
        '3': ['301', '302', '303', '304', '305', '306', '307', '308', '309', '310', '311', '312', '313', '314', '315', '316', '317', '318', '319', '320', '321', '322', '323', '324', '325', '326'],
        '4': ['401', '402', '403', '404', '405', '406', '407', '408', '409', '410', '411', '412', '413', '414', '415', '416', '417', '418', '419', '420', '421', '422', '423', '424', '425', '426', '427', '428', '429', '430', '431', '432', '433', '434', '435', '436', '437', '438', '439', '440', '441', '442', '443', '444', '445', '446', '447', '448', '449', '450', '451'],
        '5': ['501', '502', '503', '504', '505', '506', '507', '508', '509', '510', '511', '512', '513', '514', '515', '516', '517', '518', '519', '520', '521', '522', '523', '524', '525', '526', '527', '528', '529', '530', '531', '532', '533', '534', '535', '536', '537', '538', '539', '540', '541', '542', '543', '544', '545', '546', '547', '548', '549', '550', '551'],
        '6': ['601', '602', '603', '604', '606', '607', '608', '609', '610', '611', '612', '613', '614', '615', '616', '617', '618', '619', '620', '621', '622', '623', '624', '625', '626', '627', '628', '629', '630', '631', '632', '633', '634', '635', '636', '637', '638', '639', '640'],
        '7': ['701', '702', '705', '706', '707', '708', '709', '710', '711', '712', '713', '714', '715', '716', '718', '719', '720', '721', '722', '723', '724', '725', '726'],
        'A': ['A02', 'A03', 'A05', 'A06', 'A07', 'A09', 'A10', 'A11', 'A12', 'A14', 'A15', 'A16', 'A17', 'A18', 'A19', 'A20', 'A21', 'A22', 'A24', 'A25', 'A27', 'A28', 'A30', 'A31', 'A32', 'A33', 'A34', 'A36', 'A38', 'A40', 'A41', 'A42', 'A43', 'A44', 'A45', 'A46', 'A47', 'A48', 'A49', 'A50', 'A51', 'A52', 'A53', 'A54', 'A55', 'A57', 'A59', 'A60', 'A61', 'A63', 'A64', 'A65'],
        'B': ['D14', 'D15', 'D16', 'D17', 'D20', 'D21', 'D22', 'D24', 'D25', 'D26', 'D27', 'D28', 'D29', 'D30', 'D31', 'D32', 'D33', 'D34', 'D35', 'D37', 'D38', 'D39', 'D40', 'D41', 'D42', 'D43', 'R30', 'R31', 'R32', 'R33', 'R34', 'R35', 'R36'],
        'C': ['A02', 'A03', 'A05', 'A06', 'A07', 'A09', 'A10', 'A11', 'A12', 'A14', 'A15', 'A16', 'A17', 'A18', 'A19', 'A20', 'A21', 'A22', 'A24', 'A25', 'A27', 'A28', 'A30', 'A31', 'A32', 'A33', 'A34', 'A36', 'A38', 'A40', 'A41', 'A42', 'A43'],
        'D': ['D01', 'D03', 'D04', 'D05', 'D06', 'D07', 'D08', 'D09', 'D10', 'D11', 'D12', 'D13', 'D14', 'D15', 'D16', 'D17', 'D20', 'D21', 'D22', 'D24', 'D25', 'D26', 'D27', 'D28', 'D29', 'D30', 'D31', 'D32', 'D33', 'D34', 'D35', 'D37', 'D38', 'D39', 'D40', 'D41', 'D42', 'D43'],
        'E': ['F06', 'F07', 'F09', 'F11', 'F12', 'F14', 'F15', 'F16', 'F18', 'F20', 'F21', 'F22', 'F23', 'G14', 'G21', 'G08', 'G07', 'G06', 'G05'],
        'F': ['F01', 'F02', 'F03', 'F04', 'F05', 'F06', 'F07', 'F09', 'F11', 'F12', 'F14', 'F15', 'F16', 'F18', 'F20', 'F21', 'F22', 'F23', 'F24', 'F25', 'F26', 'F27', 'F29', 'F30', 'F31', 'F32', 'F33', 'F34', 'F35', 'F36', 'F38', 'F39'],
        'G': ['G22', 'G24', 'G26', 'G28', 'G29', 'G30', 'G31', 'G32', 'G33', 'G34', 'G35', 'G36'],
        'J': ['J12', 'J13', 'J14', 'J15', 'J16', 'J17', 'J19', 'J20', 'J21', 'J22', 'J23', 'J24', 'J27', 'J28', 'J29', 'J30', 'J31'],
        'L': ['L01', 'L02', 'L03', 'L05', 'L06', 'L08', 'L10', 'L11', 'L12', 'L13', 'L14', 'L15', 'L16', 'L17', 'L19', 'L20', 'L21', 'L22', 'L24', 'L25', 'L26', 'L27', 'L28', 'L29'],
        'M': ['M01', 'M04', 'M05', 'M06', 'M08', 'M09', 'M10', 'M11', 'M12', 'M13', 'M14', 'M16', 'M18', 'M19', 'M20', 'M21', 'M22', 'M23'],
        'N': ['R01', 'R03', 'R04', 'R05', 'R06', 'R08', 'R09', 'R11', 'R13', 'R14', 'R15', 'R16', 'R17', 'R18', 'R19', 'R20', 'R21', 'R22', 'R23', 'R24', 'R25', 'R26', 'R27', 'R28', 'R29', 'R30', 'R31', 'R32', 'R33', 'R34', 'R35', 'R36', 'R39', 'R40', 'R41', 'R42', 'R43', 'R44', 'R45'],
        'Q': ['Q01', 'Q03', 'Q04', 'Q05', 'Q06', 'Q07', 'Q08', 'Q09', 'Q10', 'Q11', 'Q12', 'Q13', 'Q14', 'Q15', 'Q16', 'Q17', 'Q18', 'Q19', 'Q20', 'Q21', 'Q22', 'Q23', 'Q24', 'Q25', 'Q26', 'Q27', 'Q28', 'Q29', 'Q30', 'Q31'],
        'R': ['R01', 'R03', 'R04', 'R05', 'R06', 'R08', 'R09', 'R11', 'R13', 'R14', 'R15', 'R16', 'R17', 'R18', 'R19', 'R20', 'R21', 'R22', 'R23', 'R24', 'R25', 'R26', 'R27', 'R28', 'R29', 'R30', 'R31', 'R32', 'R33', 'R34', 'R35', 'R36', 'R39', 'R40', 'R41', 'R42', 'R43', 'R44', 'R45'],
        'W': ['R01', 'R03', 'R04', 'R05', 'R06', 'R08', 'R09', 'R11', 'R13', 'R14', 'R15', 'R16', 'R17', 'R18', 'R19', 'R20', 'R21', 'R22', 'R23', 'R24', 'R25', 'R26', 'R27', 'R28', 'R29', 'R30', 'R31', 'R32', 'R33', 'R34', 'R35', 'R36'],
        'Z': ['J12', 'J13', 'J14', 'J15', 'J16', 'J17', 'J19', 'J20', 'J21', 'J22', 'J23', 'J24', 'J27', 'J28', 'J29', 'J30', 'J31'],

        # Shuttle Services
        'H': ['H01', 'H02', 'H03', 'H04', 'H06', 'H07', 'H08', 'H09', 'H10', 'H11', 'H12', 'H13', 'H14', 'H15'],  # Rockaway
        'FS': ['D26', 'S01', 'S03', 'S04'],  # Franklin
        'GS': ['901', '902'],  # Times Square

        # Staten Island Railway
        'SIR': ['S09', 'S11', 'S13', 'S14', 'S15', 'S16', 'S17', 'S18', 'S19', 'S20', 'S21', 'S22', 'S23', 'S24', 'S25', 'S26', 'S27', 'S28', 'S29', 'S30', 'S31']
    }
    
    # Get all stops that this line shares with other lines
    all_stops = set()
    shared_with = {}
    
    # First add this line's stops
    if line in specific_line_stops:
        all_stops.update(specific_line_stops[line])
    
    # Then find shared stops with other lines
    for other_line, other_stops in specific_line_stops.items():
        if other_line != line:
            # Find stops that appear in both lines
            common_stops = set(specific_line_stops[line]) & set(other_stops)
            if common_stops:
                # Add these stops and track which line they're shared with
                for stop in common_stops:
                    if stop not in shared_with:
                        shared_with[stop] = []
                    shared_with[stop].append(other_line)
    
    lines_stations = parse_stops(r"stops.txt", specific_line_stops)
    
    # Create the list of stations including shared stops
    stops = []
    for stop_id in sorted(all_stops):
        if stop_id in lines_stations:
            stop = lines_stations[stop_id].copy()
            if stop_id in shared_with:
                stop['shared_with'] = sorted(shared_with[stop_id])
            stops.append(stop)
    
    settings = session.get('settings', DEFAULT_SETTINGS)
    return render_template('service.html', line=line, stops=stops, settings=settings)

@app.route('/traininfo/<stop_id>')
def train_info(stop_id):
    stop_name = get_stop_name(stop_id)
    if not stop_name:
        return "Stop not found", 404

    lines_stations = parse_stops(r"stops.txt")
    train_info = get_upcoming_trains_for_stop(stop_id, lines_stations)
    transfers = get_transfers_for_stop(stop_id)

    # Get the user's settings or use defaults
    settings = session.get('settings', {
        'text_color': '#39FF14',
        'glow_strength': '10'
    })

    return render_template('traininfo.html', 
                         stop_name=stop_name,
                         train_info=train_info,
                         transfers=transfers,
                         settings=settings)

@app.route('/get_stops/<service>', methods=['GET'])
def get_stops(service):
    lines_stations = parse_stops(r"stops.txt")
    stops = lines_stations.get(service, [])
    return jsonify(stops)

@app.route('/search', methods=['POST'])
def search():
    parent_station = request.form['parent_station']
    lines_stations = parse_stops(r"stops.txt")
    
    train_info = get_upcoming_trains_for_stop(parent_station, lines_stations)
    transfers = get_transfers_for_stop(parent_station)

    lines_info = set()
    for line, stations in lines_stations.items():
        for station in stations:
            if station["stop_id"] == parent_station:
                lines_info.add(line)

    stop_name = get_stop_name(parent_station)

    settings = session.get('settings', DEFAULT_SETTINGS)
    return render_template('index.html',
                         stop_name=stop_name,
                         train_info=train_info,
                         lines_info=lines_info,
                         transfers=transfers,
                         settings=settings)

@app.route('/get_train_info', methods=['GET'])
def get_train_info():
    stop_id = request.args.get('stop_id')
    lines_stations = parse_stops(r"stops.txt")
    
    train_info = get_upcoming_trains_for_stop(stop_id, lines_stations)
    stop_name = get_stop_name(stop_id)
    transfers = get_transfers_for_stop(stop_id)

    return jsonify({
        'stop_name': stop_name,
        'train_info': train_info,
        'transfers': transfers
    })

@app.route('/settings', methods=['GET', 'POST'])
def settings():
    if request.method == 'POST':
        # Update settings
        new_settings = {
            'text_color': request.form.get('text_color', DEFAULT_SETTINGS['text_color']),
            'glow_strength': request.form.get('glow_strength', DEFAULT_SETTINGS['glow_strength'])
        }
        session['settings'] = new_settings
        return redirect(url_for('index'))
    
    # Get current settings from session or use defaults
    settings = session.get('settings', DEFAULT_SETTINGS)
    return render_template('settings.html', settings=settings)

@app.route('/stop/<stop_id>')
def stop(stop_id):
    url = f"https://demo.transiter.dev/systems/us-ny-subway/stops/{stop_id}"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        
        station_name = data.get('name', 'Unknown Station')
        
        # Get the lines_stations data
        lines_stations = parse_stops(r"stops.txt")
        
        # Get upcoming trains
        train_info = get_upcoming_trains_for_stop(stop_id, lines_stations)
        
        # Calculate arrival times
        current_time = time.time()
        for info in train_info:
            if info['departure_time'] is not None:
                arrival_time_sec = int(info['departure_time']) - current_time
                info['arrival_time'] = max(1, int(arrival_time_sec / 60)) if arrival_time_sec > 0 else None
            else:
                info['arrival_time'] = None
            
            # Extract just the route ID (number or letter)
            info['route_id'] = info['route_name'].split()[0]

        # Sort by arrival time
        train_info.sort(key=lambda x: x['arrival_time'] if x['arrival_time'] is not None else float('inf'))
        
        # Get transfers and headways
        transfers = get_transfers_for_stop(stop_id)
        headways = get_headways_for_stop(stop_id)
        
        settings = session.get('settings', DEFAULT_SETTINGS)
        return render_template('traininfo.html', 
                            station_name=station_name,
                            trains=train_info,
                            transfers=transfers,
                            headways=headways,
                            settings=settings)
    except requests.exceptions.RequestException as e:
        print(f"Error fetching stop info for {stop_id}: {e}")
        return "Station not found", 404

@app.context_processor
def inject_settings():
    # Make settings available to all templates
    settings = session.get('settings', DEFAULT_SETTINGS)
    return {
        'text_color': settings['text_color'],
        'glow_strength': settings['glow_strength']
    }

if __name__ == '__main__':
    app.run(debug=True, port=5001, host='0.0.0.0')
