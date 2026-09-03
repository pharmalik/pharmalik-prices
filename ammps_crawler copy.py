#!/usr/bin/env python3
"""
Extracteur AMMPS -> fichier JSON compatible "Mise à jour médicaments" de Pharmalik.

v2.0 — CORRIGÉ après un premier échec réel (0 résultats en v1). La première
version avait été construite à partir de contenu déjà converti en texte lisible,
qui ne correspond PAS au HTML brut réellement reçu par `requests`. La vraie
structure a été retrouvée en inspectant le fichier HTML brut sauvegardé
localement (debug_fetch.py) et vérifiée avec l'utilisateur avant d'écrire ce
parseur.

Structure HTML réelle vérifiée:
    <div class="modal" id="medicamentModal{ID}">
      <h5 class="modal-title">NOM</h5>
      ...
      <div class="ammps-modal-grid">
        <div class="ammps-modal-item">
          <span class="ammps-modal-label">Dosage</span>
          <span class="ammps-modal-value">250 MG</span>
        </div>
        ... (EPI, Forme, Présentation, Statut commercialisation, PPV, PH)
      </div>
    </div>

USAGE:
    pip3 install requests beautifulsoup4
    python3 ammps_crawler.py 20      # test sur 20 pages d'abord
    python3 ammps_crawler.py         # extraction complète (826 pages, ~14 min)
    -> produit ammps_full_update.json
    -> Pharmalik: Paramètres > Mise à jour des médicaments > importer ce fichier
"""
import requests
from bs4 import BeautifulSoup
import json
import re
import time
import sys
from datetime import date

BASE_URL = "https://ammps.gov.ma/recherche-medicaments"
TOTAL_PAGES = 826
OUTPUT_FILE = "ammps_full_update.json"
DELAY_BETWEEN_REQUESTS = 1.0
MAX_RETRIES = 3

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def parse_ammps_price(raw):
    """'4.303.00 DH' -> 4303.00 ; '10,70 DH' -> 10.70 ; 'SANS PPV DH' -> None"""
    if not raw:
        return None
    raw = raw.strip()
    if "SANS" in raw.upper():
        return None
    raw = raw.replace("DH", "").strip().replace(",", ".")
    parts = raw.split(".")
    if len(parts) > 2:
        integer_part = "".join(parts[:-1])
        decimal_part = parts[-1]
        raw = f"{integer_part}.{decimal_part}"
    try:
        return float(raw)
    except ValueError:
        return None


def parse_ammps_page(html_text):
    """Parseur basé sur la VRAIE structure HTML vérifiée: chaque médicament a
    un <div class="modal" id="medicamentModal{ID}"> contenant son nom
    (h5.modal-title) et une grille <div class="ammps-modal-grid"> de paires
    label/valeur (<span class="ammps-modal-label">/<span class="ammps-modal-value">)."""
    soup = BeautifulSoup(html_text, "html.parser")
    records = []
    modals = soup.find_all("div", class_="modal", id=re.compile(r"^medicamentModal\d+$"))
    for modal in modals:
        title_tag = modal.find("h5", class_="modal-title")
        nom = title_tag.get_text(strip=True) if title_tag else None
        if not nom:
            continue

        fields = {}
        for item in modal.find_all("div", class_="ammps-modal-item"):
            label_tag = item.find("span", class_="ammps-modal-label")
            value_tag = item.find("span", class_="ammps-modal-value")
            if label_tag and value_tag:
                fields[label_tag.get_text(strip=True)] = value_tag.get_text(strip=True, separator=" ")

        ppv = parse_ammps_price(fields.get("PPV"))
        if ppv is None:
            continue  # "SANS PPV" ou champ introuvable -> rien à mettre à jour pour ce produit

        dosage = fields.get("Dosage")
        forme = fields.get("Forme")
        if dosage:
            dosage = re.sub(r"\s+", " ", dosage).strip()  # ex: "250 MBQ   /    ML" -> "250 MBQ / ML"

        records.append({
            "nom_commercial": nom,
            "ean13": None,
            "ppm": ppv,
            "dosage": dosage,
            "presentation": fields.get("Présentation"),
            "forme": forme,
            "forme_dosage": f"{forme} à {dosage}" if forme and dosage else None,
            "laboratoire": fields.get("EPI"),
            "substance_active": fields.get("Substance active"),
            "statut": fields.get("Statut commercialisation"),
            "source": "AMMPS",
            "source_reference": None,
            "date_publication": date.today().isoformat(),
            "date_effective": date.today().isoformat(),
            "fetchedAt": date.today().isoformat() + "T00:00:00Z",
            "connectorVersion": "2.0.0",
        })
    return records


def fetch_page(page_idx):
    url = f"{BASE_URL}?page={page_idx}"
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=20)
            if resp.status_code == 200:
                return resp.text
            print(f"  page {page_idx}: HTTP {resp.status_code} (tentative {attempt+1}/{MAX_RETRIES})")
        except requests.RequestException as e:
            print(f"  page {page_idx}: erreur réseau {e} (tentative {attempt+1}/{MAX_RETRIES})")
        time.sleep(2)
    print(f"  ⚠️ page {page_idx}: échec après {MAX_RETRIES} tentatives, ignorée")
    return None


def main():
    end_page = TOTAL_PAGES
    if len(sys.argv) > 1:
        end_page = int(sys.argv[1])
    print(f"Extraction AMMPS: pages 1 à {end_page} (sur {TOTAL_PAGES} au total)")
    print(f"Délai entre requêtes: {DELAY_BETWEEN_REQUESTS}s — estimation: ~{end_page * DELAY_BETWEEN_REQUESTS / 60:.1f} min\n")

    all_records = []
    for page in range(1, end_page + 1):
        html = fetch_page(page)
        if html:
            page_records = parse_ammps_page(html)
            all_records.extend(page_records)
            print(f"  page {page}/{end_page}: {len(page_records)} médicaments (total: {len(all_records)})")
        time.sleep(DELAY_BETWEEN_REQUESTS)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(all_records, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Terminé: {len(all_records)} médicaments extraits -> {OUTPUT_FILE}")
    print("Étape suivante: Pharmalik -> Paramètres -> Mise à jour des médicaments -> importer ce fichier.")


if __name__ == "__main__":
    main()
