import streamlit as st
import threading
import queue
import time
import os
import io
import pandas as pd

from gmaps_main import (
    wczytaj_historie, dopisz_do_historii,
    wyczysc_historie, usun_z_historii,
    buduj_nazwe_pliku, zapisz_excel, zapisz_excel_linkedin,
    HISTORIA_PATH, RAPORTY_DIR,
)
from gmaps_scraper import scrape_maps
from gmaps_web import scrape_website, deep_scrape_website
from linkedin_scraper import szukaj_linkedin

# ── Strona ──────────────────────────────────────────────────────────────────
st.set_page_config(page_title="Shoplet Lead Gen", page_icon="🔍", layout="wide")
st.title("🔍 Shoplet Lead Generator")

# ── Session state ────────────────────────────────────────────────────────────
for key, default in [
    ("scraping", False),
    ("msg_queue", None),
    ("results", None),
    ("excel_path", None),
    ("log_messages", []),
    ("phase_label", ""),
    ("progress_val", 0.0),
]:
    if key not in st.session_state:
        st.session_state[key] = default


# ── Background worker ────────────────────────────────────────────────────────
def run_scraping(query: str, limit: int, msg_q: queue.Queue):
    """Runs in a daemon thread. Puts (type, payload) into msg_q."""
    try:
        historia = wczytaj_historie(HISTORIA_PATH)
        msg_q.put(("log", f"Historia: {len(historia)} znanych firm."))
        os.makedirs(RAPORTY_DIR, exist_ok=True)

        # Faza 1: Google Maps
        msg_q.put(("phase", "Faza 1/3 — Google Maps"))
        msg_q.put(("log", f"Szukam '{query}' (limit={limit})…"))
        firmy = scrape_maps(query, limit=limit, already_collected=historia)
        msg_q.put(("log", f"Znaleziono {len(firmy)} nowych firm z Map."))

        if not firmy:
            msg_q.put(("done", []))
            return

        dopisz_do_historii(HISTORIA_PATH, [f["nazwa"] for f in firmy])

        # Faza 2: strony WWW
        msg_q.put(("phase", "Faza 2/3 — Scraping stron WWW"))
        total = len(firmy)
        for i, firma in enumerate(firmy):
            if firma["www"]:
                dane = scrape_website(firma["www"])
                if not firma["email"]:
                    firma["email"] = dane["email"]
                firma["nip"] = dane["nip"]
            email_info = firma["email"] or "brak e-mail"
            msg_q.put(("log", f"[{i+1}/{total}] {firma['nazwa']} — {email_info}"))
            msg_q.put(("progress", (i + 1) / total * 0.5 + 0.2))  # 20%–70%
            time.sleep(1.5)

        # Faza 2b: głębszy scraping firm z brakami
        incomplete = [f for f in firmy if not f["email"] or not f["nip"]]
        if incomplete:
            msg_q.put(("phase", f"Faza 2b/3 — Głębsze szukanie ({len(incomplete)} firm)"))
            for i, firma in enumerate(incomplete):
                dane = deep_scrape_website(firma["www"], firma["nazwa"])
                if dane["email"] and not firma["email"]:
                    firma["email"] = dane["email"]
                if dane["nip"] and not firma["nip"]:
                    firma["nip"] = dane["nip"]
                msg_q.put(
                    (
                        "log",
                        f"[{i+1}/{len(incomplete)}] {firma['nazwa']} — "
                        f"email={firma['email'] or 'brak'} nip={firma['nip'] or 'brak'}",
                    )
                )
                msg_q.put(("progress", 0.7 + (i + 1) / len(incomplete) * 0.25))  # 70%–95%
                time.sleep(1.5)

        # Faza 3: Zapis Excel
        msg_q.put(("phase", "Faza 3/3 — Zapis Excel"))
        nazwa_pliku = buduj_nazwe_pliku(query)
        zapisz_excel(firmy, nazwa_pliku)
        msg_q.put(("file", nazwa_pliku))
        msg_q.put(("log", f"Zapisano: {nazwa_pliku}"))
        msg_q.put(("progress", 1.0))
        msg_q.put(("done", firmy))

    except Exception as exc:
        msg_q.put(("error", str(exc)))


# ── Helper: drain the queue into session state ────────────────────────────────
def drain_queue():
    q = st.session_state.msg_queue
    if q is None:
        return
    while True:
        try:
            msg_type, payload = q.get_nowait()
        except queue.Empty:
            break

        if msg_type == "log":
            st.session_state.log_messages.append(payload)
        elif msg_type == "phase":
            st.session_state.phase_label = payload
            st.session_state.log_messages.append(f"**{payload}**")
        elif msg_type == "progress":
            st.session_state.progress_val = float(payload)
        elif msg_type == "file":
            st.session_state.excel_path = payload
        elif msg_type == "done":
            st.session_state.results = payload
            st.session_state.scraping = False
        elif msg_type == "error":
            st.session_state.log_messages.append(f"❌ BŁĄD: {payload}")
            st.session_state.scraping = False


# ── Session state dla LinkedIn ───────────────────────────────────────────────
for key, default in [
    ("li_scraping", False),
    ("li_msg_queue", None),
    ("li_results", None),
    ("li_excel_path", None),
    ("li_log_messages", []),
    ("li_progress_val", 0.0),
]:
    if key not in st.session_state:
        st.session_state[key] = default


# ── Background worker LinkedIn ───────────────────────────────────────────────
def run_linkedin(query: str, limit: int, msg_q: queue.Queue):
    """Runs in a daemon thread. Puts (type, payload) into msg_q."""
    try:
        msg_q.put(("log", f"Szukam na LinkedIn: '{query}' (limit={limit})…"))
        msg_q.put(("progress", 0.1))

        kontakty = szukaj_linkedin(query, limit=limit)
        msg_q.put(("log", f"Znaleziono {len(kontakty)} profili."))
        msg_q.put(("progress", 0.8))

        if not kontakty:
            msg_q.put(("done", []))
            return

        os.makedirs(RAPORTY_DIR, exist_ok=True)
        slug = query.replace(' ', '_')[:40]
        from datetime import date
        nazwa_pliku = os.path.join(RAPORTY_DIR, f"LinkedIn_{slug}_{date.today().isoformat()}.xlsx")
        zapisz_excel_linkedin(kontakty, nazwa_pliku)
        msg_q.put(("file", nazwa_pliku))
        msg_q.put(("log", f"Zapisano: {nazwa_pliku}"))
        msg_q.put(("progress", 1.0))
        msg_q.put(("done", kontakty))

    except Exception as exc:
        msg_q.put(("error", str(exc)))


def drain_linkedin_queue():
    q = st.session_state.li_msg_queue
    if q is None:
        return
    while True:
        try:
            msg_type, payload = q.get_nowait()
        except queue.Empty:
            break
        if msg_type == "log":
            st.session_state.li_log_messages.append(payload)
        elif msg_type == "progress":
            st.session_state.li_progress_val = float(payload)
        elif msg_type == "file":
            st.session_state.li_excel_path = payload
        elif msg_type == "done":
            st.session_state.li_results = payload
            st.session_state.li_scraping = False
        elif msg_type == "error":
            st.session_state.li_log_messages.append(f"❌ BŁĄD: {payload}")
            st.session_state.li_scraping = False


# ── Tabs ─────────────────────────────────────────────────────────────────────
tab_search, tab_linkedin, tab_history = st.tabs([
    "🔎 Google Maps",
    "🔗 LinkedIn Search",
    "📁 Historia raportów",
])


# ════════════════════════════════════════════════════════════════════════════
# TAB 1 — Google Maps
# ════════════════════════════════════════════════════════════════════════════
with tab_search:
    col_left, col_right = st.columns([3, 1])
    with col_left:
        query_input = st.text_input(
            "Fraza wyszukiwania",
            placeholder="np. biuro rachunkowe wrocław",
            disabled=st.session_state.scraping,
        )
    with col_right:
        limit_input = st.number_input(
            "Limit firm",
            min_value=1,
            max_value=200,
            value=20,
            disabled=st.session_state.scraping,
        )

    start_btn = st.button(
        "▶ Szukaj",
        disabled=st.session_state.scraping or not query_input,
        type="primary",
    )

    # Uruchom scrapowanie
    if start_btn:
        st.session_state.scraping = True
        st.session_state.results = None
        st.session_state.excel_path = None
        st.session_state.log_messages = []
        st.session_state.phase_label = ""
        st.session_state.progress_val = 0.0

        msg_q = queue.Queue()
        st.session_state.msg_queue = msg_q

        t = threading.Thread(
            target=run_scraping,
            args=(query_input, int(limit_input), msg_q),
            daemon=True,
        )
        t.start()
        st.rerun()

    # Pasek postępu + log (widoczny podczas scrapowania lub gdy są wyniki)
    if st.session_state.scraping or st.session_state.log_messages:
        st.divider()

        if st.session_state.phase_label:
            st.caption(f"⏳ {st.session_state.phase_label}")

        progress_bar = st.progress(st.session_state.progress_val)

        log_box = st.empty()

        # Polling — odśwież kolejkę
        if st.session_state.scraping:
            drain_queue()
            progress_bar.progress(st.session_state.progress_val)

        # Wyświetl ostatnie 30 wpisów logu
        with log_box.container():
            for line in st.session_state.log_messages[-30:]:
                st.markdown(line)

        if st.session_state.scraping:
            time.sleep(1.2)
            st.rerun()

    # Wyniki po zakończeniu
    if st.session_state.results is not None:
        firmy = st.session_state.results
        st.divider()

        if not firmy:
            st.warning("Brak wyników dla podanej frazy.")
        else:
            col_status, col_reset = st.columns([4, 1])
            with col_status:
                st.success(f"✅ Znaleziono **{len(firmy)}** firm.")
            with col_reset:
                if st.button("🔄 Nowe wyszukiwanie", type="secondary"):
                    st.session_state.results = None
                    st.session_state.log_messages = []
                    st.session_state.excel_path = None
                    st.session_state.phase_label = ""
                    st.session_state.progress_val = 0.0
                    st.rerun()

            df = pd.DataFrame(
                [
                    {
                        "Nazwa Firmy": f["nazwa"],
                        "Adres": f["adres"],
                        "Telefon": f["telefon"],
                        "Strona WWW": f["www"],
                        "E-mail": f["email"],
                        "NIP": f["nip"],
                    }
                    for f in firmy
                ]
            )

            st.dataframe(df, use_container_width=True, height=400)

            # Przycisk pobierania
            if st.session_state.excel_path and os.path.exists(st.session_state.excel_path):
                with open(st.session_state.excel_path, "rb") as fh:
                    excel_bytes = fh.read()
                st.download_button(
                    label="⬇ Pobierz Excel",
                    data=excel_bytes,
                    file_name=os.path.basename(st.session_state.excel_path),
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    type="primary",
                )
            else:
                # Fallback: generuj Excel w pamięci
                buf = io.BytesIO()
                df.to_excel(buf, index=False)
                st.download_button(
                    label="⬇ Pobierz Excel",
                    data=buf.getvalue(),
                    file_name="wyniki.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    type="primary",
                )


# ════════════════════════════════════════════════════════════════════════════
# TAB 2 — LinkedIn Search
# ════════════════════════════════════════════════════════════════════════════
with tab_linkedin:
    col_left, col_right = st.columns([3, 1])
    with col_left:
        li_query = st.text_input(
            "Fraza wyszukiwania LinkedIn",
            placeholder="np. kierownik działu zakupów Wrocław",
            disabled=st.session_state.li_scraping,
            key="li_query_input",
        )
    with col_right:
        li_limit = st.number_input(
            "Limit profili",
            min_value=1,
            max_value=100,
            value=20,
            disabled=st.session_state.li_scraping,
            key="li_limit_input",
        )

    li_start_btn = st.button(
        "▶ Szukaj na LinkedIn",
        disabled=st.session_state.li_scraping or not li_query,
        type="primary",
        key="li_start_btn",
    )

    if li_start_btn:
        st.session_state.li_scraping = True
        st.session_state.li_results = None
        st.session_state.li_excel_path = None
        st.session_state.li_log_messages = []
        st.session_state.li_progress_val = 0.0

        msg_q = queue.Queue()
        st.session_state.li_msg_queue = msg_q

        t = threading.Thread(
            target=run_linkedin,
            args=(li_query, int(li_limit), msg_q),
            daemon=True,
        )
        t.start()
        st.rerun()

    if st.session_state.li_scraping or st.session_state.li_log_messages:
        st.divider()
        li_progress_bar = st.progress(st.session_state.li_progress_val)
        li_log_box = st.empty()

        if st.session_state.li_scraping:
            drain_linkedin_queue()
            li_progress_bar.progress(st.session_state.li_progress_val)

        with li_log_box.container():
            for line in st.session_state.li_log_messages[-30:]:
                st.markdown(line)

        if st.session_state.li_scraping:
            time.sleep(1.2)
            st.rerun()

    if st.session_state.li_results is not None:
        kontakty = st.session_state.li_results
        st.divider()

        if not kontakty:
            st.warning("Brak wyników dla podanej frazy.")
        else:
            col_status, col_reset = st.columns([4, 1])
            with col_status:
                st.success(f"✅ Znaleziono **{len(kontakty)}** profili.")
            with col_reset:
                if st.button("🔄 Nowe wyszukiwanie", type="secondary", key="li_reset_btn"):
                    st.session_state.li_results = None
                    st.session_state.li_log_messages = []
                    st.session_state.li_excel_path = None
                    st.session_state.li_progress_val = 0.0
                    st.rerun()

            df_li = pd.DataFrame(kontakty)
            df_li.columns = ['Imię i Nazwisko', 'Stanowisko', 'Firma', 'Lokalizacja', 'LinkedIn URL']
            st.dataframe(df_li, use_container_width=True, height=400)

            if st.session_state.li_excel_path and os.path.exists(st.session_state.li_excel_path):
                with open(st.session_state.li_excel_path, "rb") as fh:
                    st.download_button(
                        label="⬇ Pobierz Excel",
                        data=fh.read(),
                        file_name=os.path.basename(st.session_state.li_excel_path),
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        type="primary",
                        key="li_download_btn",
                    )
            else:
                buf = io.BytesIO()
                df_li.to_excel(buf, index=False)
                st.download_button(
                    label="⬇ Pobierz Excel",
                    data=buf.getvalue(),
                    file_name="linkedin_wyniki.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    type="primary",
                    key="li_download_fallback_btn",
                )


# ════════════════════════════════════════════════════════════════════════════
# TAB 3 — historia raportów
# ════════════════════════════════════════════════════════════════════════════
with tab_history:
    raporty_dir = RAPORTY_DIR
    if not os.path.exists(raporty_dir):
        st.info("Brak katalogu Raporty/. Uruchom najpierw wyszukiwanie.")
    else:
        files = sorted(
            [f for f in os.listdir(raporty_dir) if f.endswith(".xlsx")],
            reverse=True,
        )

        if not files:
            st.info("Brak zapisanych raportów.")
        else:
            st.markdown(f"Znaleziono **{len(files)}** raportów:")

            selected = st.selectbox(
                "Wybierz raport do podglądu",
                options=files,
                index=0,
            )

            selected_path = os.path.join(raporty_dir, selected)

            col_preview, col_dl = st.columns([6, 1])

            with col_dl:
                with open(selected_path, "rb") as fh:
                    st.download_button(
                        label="⬇ Pobierz",
                        data=fh.read(),
                        file_name=selected,
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )

            with col_preview:
                try:
                    df_hist = pd.read_excel(selected_path)
                    st.dataframe(df_hist, use_container_width=True, height=450)
                    st.caption(f"{len(df_hist)} wierszy · {selected_path}")
                except Exception as e:
                    st.error(f"Nie można odczytać pliku: {e}")

            # Podsumowanie wszystkich raportów
            st.divider()
            st.subheader("Wszystkie raporty")
            summary_rows = []
            for fname in files:
                fpath = os.path.join(raporty_dir, fname)
                try:
                    tmp = pd.read_excel(fpath)
                    n = len(tmp)
                    emails = tmp["E-mail"].notna().sum() if "E-mail" in tmp.columns else 0
                    nips = tmp["NIP"].notna().sum() if "NIP" in tmp.columns else 0
                except Exception:
                    n = emails = nips = "?"
                size_kb = round(os.path.getsize(fpath) / 1024, 1)
                summary_rows.append(
                    {
                        "Plik": fname,
                        "Firm": n,
                        "E-maile": emails,
                        "NIP-y": nips,
                        "Rozmiar (KB)": size_kb,
                    }
                )
            st.dataframe(pd.DataFrame(summary_rows), use_container_width=True)

    # ── Zarządzanie historią firm ─────────────────────────────────────────
    st.divider()
    st.subheader("🗑 Zarządzaj historią firm")

    historia_set = wczytaj_historie(HISTORIA_PATH)
    st.caption(f"W historii jest **{len(historia_set)}** firm (służą do pomijania duplikatów w kolejnych wyszukiwaniach).")

    if historia_set:
        historia_lista = sorted(historia_set)

        with st.expander("Pokaż i usuń wybrane firmy z historii"):
            do_usuniecia = st.multiselect(
                "Zaznacz firmy do usunięcia",
                options=historia_lista,
                placeholder="Wyszukaj firmę…",
            )
            if do_usuniecia:
                if st.button(f"🗑 Usuń zaznaczone ({len(do_usuniecia)})", type="secondary", key="usun_wybrane_btn"):
                    usun_z_historii(HISTORIA_PATH, do_usuniecia)
                    st.success(f"Usunięto {len(do_usuniecia)} firm z historii.")
                    st.rerun()

        st.warning("Wyczyszczenie całej historii spowoduje, że następne wyszukiwanie może znaleźć te same firmy ponownie.")
        if st.button("🗑 Wyczyść całą historię", type="secondary", key="wyczysc_btn"):
            wyczysc_historie(HISTORIA_PATH)
            st.success("Historia została wyczyszczona.")
            st.rerun()
    else:
        st.info("Historia jest pusta.")
