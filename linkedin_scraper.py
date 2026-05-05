import re
import time
import random

from ddgs import DDGS


def _parsuj_wynik(tytul: str, url: str, opis: str) -> dict:
    """Wyciąga dane kontaktowe z jednego wyniku DDG."""
    imie_nazwisko = ''
    stanowisko = ''
    firma = ''
    lokalizacja = ''

    # Tytuł LinkedIn ma postać: "Imię Nazwisko - Stanowisko - Firma | LinkedIn"
    # lub: "Imię Nazwisko | LinkedIn"
    tytul_clean = re.sub(r'\s*\|\s*LinkedIn.*$', '', tytul, flags=re.IGNORECASE).strip()
    czesci = [c.strip() for c in tytul_clean.split(' - ')]

    if czesci:
        imie_nazwisko = czesci[0]
    if len(czesci) >= 2:
        stanowisko = czesci[1]
    if len(czesci) >= 3:
        firma = czesci[2]

    # Lokalizacja często pojawia się w opisie, np. "Wrocław, Dolnośląskie, Polska"
    lok_match = re.search(
        r'([A-ZŁŚÓĆŻŹŃ][a-złśóćżźń]+(?:\s[A-ZŁŚÓĆŻŹŃ][a-złśóćżźń]+)*'
        r'(?:,\s*[A-ZŁŚÓĆŻŹŃ][a-złśóćżźń]+)*(?:,\s*Polska)?)',
        opis or '',
    )
    if lok_match:
        lokalizacja = lok_match.group(1)

    return {
        'imie_nazwisko': imie_nazwisko,
        'stanowisko': stanowisko,
        'firma': firma,
        'lokalizacja': lokalizacja,
        'linkedin_url': url,
    }


def szukaj_linkedin(query: str, limit: int = 20) -> list:
    """
    Wyszukuje profile LinkedIn pasujące do zapytania.

    Zwraca listę słowników:
        {imie_nazwisko, stanowisko, firma, lokalizacja, linkedin_url}
    """
    ddgs_query = f'{query} site:linkedin.com/in'
    wyniki = []

    with DDGS() as ddgs:
        for r in ddgs.text(ddgs_query, max_results=limit * 2):
            url = r.get('href', '')
            # Akceptuj tylko URL-e prowadzące bezpośrednio do profilu (/in/)
            if 'linkedin.com/in/' not in url:
                continue

            kontakt = _parsuj_wynik(
                tytul=r.get('title', ''),
                url=url,
                opis=r.get('body', ''),
            )
            # Pomiń wyniki bez imienia
            if not kontakt['imie_nazwisko']:
                continue

            wyniki.append(kontakt)

            if len(wyniki) >= limit:
                break

            time.sleep(random.uniform(1.5, 3.0))

    return wyniki
