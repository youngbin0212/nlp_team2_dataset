import yt_dlp, json

URLS = [json.loads(l)['url'] for l in open('lol_url_successed.jsonl', encoding='utf-8')][:3]

for clients in (['web'], ['mweb'], ['web', 'default'], ['tv']):
    opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'remote_components': ['ejs:github'],
        'extractor_args': {'youtube': {'player_client': clients}},
    }
    print(f'=== player_client={clients} ===')
    with yt_dlp.YoutubeDL(opts) as ydl:
        for u in URLS:
            try:
                info = ydl.extract_info(u, download=False)
                hm = info.get('heatmap')
                print(f"  {info['id']} | heatmap={len(hm) if hm else 0} | formats={len(info.get('formats') or [])}")
            except Exception as e:
                print(f"  {u} | ERR {str(e)[:120]}")
