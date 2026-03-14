import requests
from bs4 import BeautifulSoup
import re

EMAIL_RE = re.compile(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}')
NIP_RE = re.compile(r'\bNIP[\s:\-]*(\d[\d\s\-]{8,12}\d)\b', re.IGNORECASE)
NIP_BARE_RE = re.compile(r'\b(\d{3}[-\s]?\d{3}[-\s]?\d{2}[-\s]?\d{2})\b')

HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/122.0.0.0 Safari/537.36'
    )
}


def _extract(text: str) -> dict:
    email_match = EMAIL_RE.search(text)
    email = email_match.group(0) if email_match else ''

    nip_match = NIP_RE.search(text)
    if nip_match:
        raw = nip_match.group(1)
        nip = re.sub(r'[\s\-]', '', raw)[:10]
    else:
        bare_match = NIP_BARE_RE.search(text)
        nip = re.sub(r'[\s\-]', '', bare_match.group(1))[:10] if bare_match else ''

    return {'email': email, 'nip': nip}


def _fetch_raw(url: str) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=8)
    resp.raise_for_status()
    return resp.text


def _fetch_text(url: str) -> str:
    soup = BeautifulSoup(_fetch_raw(url), 'html.parser')
    return soup.get_text(separator=' ')


def _extract_jsonld(html: str) -> dict:
    import json
    data = {'email': '', 'nip': ''}
    soup = BeautifulSoup(html, 'html.parser')
    for script in soup.find_all('script', type='application/ld+json'):
        try:
            obj = json.loads(script.string or '{}')
            items = obj if isinstance(obj, list) else [obj]
            for item in items:
                if not data['email'] and item.get('email'):
                    data['email'] = str(item['email']).strip()
                if not data['nip']:
                    tax = str(item.get('taxID', '') or item.get('vatID', '') or '')
                    if tax:
                        data['nip'] = re.sub(r'[\s\-]', '', tax)[:10]
                    else:
                        desc = str(item.get('description', ''))
                        m = NIP_RE.search(desc) or NIP_BARE_RE.search(desc)
                        if m:
                            data['nip'] = re.sub(r'[\s\-]', '', m.group(1))[:10]
        except Exception:
            pass
    return data


def _ddg_search_field(query: str, field: str) -> str:
    """field: 'nip' or 'email'"""
    try:
        from ddgs import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=5))
        for r in results:
            snippet = r.get('body', '') + ' ' + r.get('title', '')
            if field == 'nip':
                m = NIP_RE.search(snippet) or NIP_BARE_RE.search(snippet)
                if m:
                    return re.sub(r'[\s\-]', '', m.group(1))[:10]
            else:
                m = EMAIL_RE.search(snippet)
                if m:
                    return m.group(0)
    except Exception:
        pass
    return ''


def deep_scrape_website(url: str, nazwa: str) -> dict:
    """Drugi, bardziej agresywny przebieg dla firmy z brakującymi danymi."""
    data = {'email': '', 'nip': ''}

    # Etap A: JSON-LD
    html = ''
    if url:
        try:
            html = _fetch_raw(url)
            jld = _extract_jsonld(html)
            data['email'] = jld['email']
            data['nip'] = jld['nip']
        except Exception:
            html = ''

        # Etap B: Wyczerpujące przeszukanie podstron (wszystkie linki same-domain)
        if not data['email'] or not data['nip']:
            try:
                from urllib.parse import urljoin
                base = url.rstrip('/')
                soup = BeautifulSoup(html or _fetch_raw(url), 'html.parser')
                all_links = []
                seen = {base}
                for a in soup.find_all('a', href=True):
                    full = urljoin(base, a['href']).rstrip('/')
                    if full.startswith(base) and full not in seen:
                        seen.add(full)
                        all_links.append(full)
                # Kontakt/o-nas pierwsze
                all_links.sort(key=lambda u: 0 if any(
                    kw in u.lower() for kw in ['kontakt', 'contact', 'o-nas', 'firma', 'about']
                ) else 1)
                for suburl in all_links[:15]:
                    if data['email'] and data['nip']:
                        break
                    try:
                        sub_html = _fetch_raw(suburl)
                        jld2 = _extract_jsonld(sub_html)
                        if jld2['email'] and not data['email']:
                            data['email'] = jld2['email']
                        if jld2['nip'] and not data['nip']:
                            data['nip'] = jld2['nip']
                        if not data['email'] or not data['nip']:
                            sub_text = BeautifulSoup(sub_html, 'html.parser').get_text(separator=' ')
                            d2 = _extract(sub_text)
                            if d2['email'] and not data['email']:
                                data['email'] = d2['email']
                            if d2['nip'] and not data['nip']:
                                data['nip'] = d2['nip']
                    except Exception:
                        pass
            except Exception:
                pass

    # Etap C: DDG search jako ostateczny fallback
    if not data['nip']:
        data['nip'] = _ddg_search_field(f'"{nazwa}" NIP', 'nip')
    if not data['email']:
        data['email'] = _ddg_search_field(f'"{nazwa}" email kontakt', 'email')

    return data


def scrape_website(url: str) -> dict:
    try:
        text = _fetch_text(url)
        data = _extract(text)

        if not data['email'] or not data['nip']:
            from urllib.parse import urljoin
            base = url.rstrip('/')
            extra_paths = ['/kontakt', '/contact', '/o-nas', '/o-firmie',
                           '/regulamin', '/polityka-prywatnosci', '/stopka', '/rodo']
            try:
                soup = BeautifulSoup(_fetch_raw(url), 'html.parser')
                for a in soup.find_all('a', href=True):
                    href = a['href'].lower()
                    if any(kw in href for kw in ['kontakt', 'contact', 'about', 'o-nas', 'firma']):
                        full = urljoin(base, a['href']).rstrip('/')
                        if full.startswith(base) and full not in extra_paths:
                            extra_paths.append(full)
            except Exception:
                pass

            for path in extra_paths:
                if data['email'] and data['nip']:
                    break
                try:
                    suburl = path if path.startswith('http') else base + path
                    text2 = _fetch_text(suburl)
                    d2 = _extract(text2)
                    if d2['email'] and not data['email']:
                        data['email'] = d2['email']
                    if d2['nip'] and not data['nip']:
                        data['nip'] = d2['nip']
                except Exception:
                    pass

        return data
    except Exception:
        return {'email': '', 'nip': ''}
