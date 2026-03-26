from credigraph import query

domains = ['mila.quebec', 'mcgill.ca', 'ox.ac.uk', 'huggingface.co', 'scholar.google.com', 'baidu.com', 'bbc.com', 'github.com']

for d in domains:
    try:
        result = query(d)
        print(f'{d}: {result}')
    except Exception as e:
        print(f'{d}: ERROR - {e}')
