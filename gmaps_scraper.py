from playwright.sync_api import sync_playwright
from urllib.parse import urlparse, parse_qs
import time
import re
import sys

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass


def _unwrap_google_url(href: str) -> str:
    """Wyciąga prawdziwy URL z przekierowania Google (google.com/url?q=...)"""
    if 'google' in href and 'url?q=' in href:
        parsed = urlparse(href)
        qs = parse_qs(parsed.query)
        if 'q' in qs:
            return qs['q'][0].rstrip('/')
    return href.rstrip('/')


def _accept_consent(page):
    try:
        btn = page.wait_for_selector(
            'button[aria-label="Zaakceptuj wszystko"], '
            'button[aria-label="Accept all"], '
            'form[action*="consent"] button',
            timeout=5000
        )
        if btn:
            btn.click()
            page.wait_for_load_state('networkidle', timeout=5000)
    except Exception:
        pass  # brak dialogu — ok


def scrape_maps(query: str, limit: int = 20, already_collected: set = None) -> list:
    if already_collected is None:
        already_collected = set()

    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()

        url = f"https://www.google.com/maps/search/{query.replace(' ', '+')}"
        page.goto(url)

        _accept_consent(page)

        try:
            page.wait_for_selector('[role="feed"]', timeout=15000)
        except Exception:
            try:
                print("[WARN] Nie znaleziono panelu wynikow. Sprawdz przegladarke.")
            except UnicodeEncodeError:
                pass
            browser.close()
            return results

        feed_el = page.query_selector('[role="feed"]')

        collected_names = set(already_collected)
        last_count = -1
        processed_indices = set()

        while len(results) < limit:
            tiles = page.query_selector_all('.hfpxzc')

            if len(tiles) == last_count:
                # No new tiles after scroll — end of results
                break
            last_count = len(tiles)

            for i, tile in enumerate(tiles):
                if len(results) >= limit:
                    break

                if i in processed_indices:
                    continue

                try:
                    tile.click()
                    page.wait_for_selector('h1.DUwDvf', timeout=8000)
                    time.sleep(1.0)  # panel async — buttony ładują się po h1
                except Exception:
                    continue

                processed_indices.add(i)

                try:
                    nazwa = page.query_selector('h1.DUwDvf')
                    nazwa = nazwa.inner_text().strip() if nazwa else ''
                except Exception:
                    nazwa = ''

                if not nazwa or nazwa in collected_names:
                    continue

                adres = ''
                for sel in ['button[data-item-type="address"]', '.Io6YTe', '[data-tooltip*="dres"]']:
                    el = page.query_selector(sel)
                    if el:
                        adres = el.inner_text().strip()
                        break

                telefon = ''
                for sel in ['button[data-item-type="phone:tel"]', 'button[data-item-type="phone"]',
                            '[data-tooltip*="numer"]', '[data-tooltip*="phone"]']:
                    el = page.query_selector(sel)
                    if el:
                        telefon = el.inner_text().strip()
                        break

                www = ''
                for sel in [
                    'a[data-item-type="authority"]',
                    '[data-item-type="authority"] a',
                    'a[aria-label*="Witryna"]',
                    'a[aria-label*="Website"]',
                    'a[aria-label*="witryn"]',
                ]:
                    el = page.query_selector(sel)
                    if el:
                        href = el.get_attribute('href') or ''
                        if href:
                            real = _unwrap_google_url(href)
                            if real and 'google.com' not in real:
                                www = real
                                break
                if not www:
                    try:
                        raw_www = page.evaluate("""
                            () => {
                                const el = document.querySelector('[data-item-type="authority"]');
                                if (!el) return '';
                                const a = el.tagName === 'A' ? el : el.querySelector('a');
                                return a ? a.href : '';
                            }
                        """) or ''
                        if raw_www:
                            real = _unwrap_google_url(raw_www)
                            if real and 'google.com' not in real:
                                www = real
                    except Exception:
                        pass

                # Rozwiń ukryte sekcje panelu (może kryć email)
                for expand_sel in [
                    'button[aria-label*="Więcej"]',
                    'button[aria-label*="więcej"]',
                    'button[aria-label*="More"]',
                    'button[aria-label*="Pokaż"]',
                ]:
                    try:
                        btn = page.query_selector(expand_sel)
                        if btn:
                            btn.click()
                            time.sleep(0.5)
                            break
                    except Exception:
                        pass

                email_maps = ''
                # 1) Selektory CSS — button i a z data-item-type
                for sel in [
                    'button[data-item-type="email"]',
                    'a[data-item-type="email"]',
                    '[href^="mailto:"]',
                    '[data-tooltip*="mail"]',
                ]:
                    el = page.query_selector(sel)
                    if el:
                        href = el.get_attribute('href') or ''
                        if href.startswith('mailto:'):
                            email_maps = href.replace('mailto:', '').split('?')[0].strip()
                        else:
                            email_maps = el.inner_text().strip()
                        if email_maps:
                            break

                # 2) JS regex-scan całego HTML panelu jako fallback
                if not email_maps:
                    try:
                        email_maps = page.evaluate("""
                            () => {
                                const panel = document.querySelector('[role="main"]') || document.body;
                                const text = panel.innerHTML;
                                const m = text.match(/mailto:([^"'?\\s<>]+)/);
                                if (m) return m[1];
                                const m2 = panel.innerText.match(/[a-zA-Z0-9._%+\\-]+@[a-zA-Z0-9.\\-]+\\.[a-zA-Z]{2,}/);
                                return m2 ? m2[0] : '';
                            }
                        """) or ''
                    except Exception:
                        pass

                firma = {
                    'nazwa': nazwa,
                    'adres': adres,
                    'telefon': telefon,
                    'www': www,
                    'email': email_maps,
                    'nip': '',
                }
                results.append(firma)
                collected_names.add(nazwa)
                try:
                    print(f"  [Maps] {len(results)}/{limit} - {nazwa} | adres={bool(adres)} tel={bool(telefon)} www={bool(www)} email={bool(email_maps)}")
                except UnicodeEncodeError:
                    pass

            if len(results) < limit:
                # Scroll down in the feed
                try:
                    feed_el.evaluate("el => { el.scrollTop += 500; }")
                    time.sleep(2)
                except Exception:
                    break

        browser.close()

    return results
