import requests, json

FIFA_HEADERS = {
    'accept': 'application/json, text/plain, */*',
    'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36',
    'referer': 'https://play.fifa.com/',
}

BASE = 'https://play.fifa.com/json/fantasy'

players = requests.get(f'{BASE}/players.json', headers=FIFA_HEADERS).json()
rounds = requests.get(f'{BASE}/rounds.json', headers=FIFA_HEADERS).json()

# Fetch stats for every player
all_stats = {}
for i, p in enumerate(players):
    try:
        stats = requests.get(f'{BASE}/player_stats/{p["id"]}.json', headers=FIFA_HEADERS).json()
        all_stats[p['id']] = stats
        if i % 50 == 0:
            print(f'{i}/{len(players)}')
    except:
        pass

# Merge into one dataset
dataset = []
for p in players:
    dataset.append({
        'id': p['id'],
        'name': p.get('knownName') or f"{p['firstName']} {p['lastName']}",
        'squad_id': p['squadId'],
        'position': p['position'],
        'price': p['price'],
        'status': p['status'],
        'total_points': p['stats']['totalPoints'],
        'avg_points': p['stats']['avgPoints'],
        'round_points': p['stats']['roundPoints'],
        'next_fixture': p['stats']['nextFixtureFromActiveRound'],
        'percent_selected': p['percentSelected'],
        'round_stats': all_stats.get(p['id'], []),
    })

with open('fifa_players_full.json', 'w', encoding='utf-8') as f:
    json.dump({'players': dataset, 'rounds': rounds}, f, indent=2, ensure_ascii=False)

print(f'Done. {len(dataset)} players saved to fifa_players_full.json')