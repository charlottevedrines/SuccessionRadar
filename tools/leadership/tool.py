"""Logique principale : lit l'input, enrichit chaque entreprise, ecrit l'output.
 
Ce fichier ne parle jamais a Internet. Il se contente d'appeler les fonctions
de api.py, dans le bon ordre, et de ranger le resultat.
"""
 
import json
from pathlib import Path
 
from api import (
    fetch_company,
    fetch_bodacc_annonces,
    extract_dirigeants,
    calculate_age,
    calculate_company_age,
    find_leadership_changes,
    estimate_tenure,
    FENETRE_RECENTE_ANNEES,
)
 
 
def load_input(path: str) -> list[dict]:
    """Ouvre le fichier JSON d'entree et verifie qu'il est valide.
 
    Chaque entreprise doit avoir 'siren' et 'nom_entreprise'.
    On accepte aussi l'ancienne ecriture "nom d'entreprise".
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
 
    if not isinstance(data, list):
        raise ValueError("Le fichier d'entree doit contenir une liste d'entreprises.")
 
    for i, company in enumerate(data):
        if "siren" not in company:
            raise ValueError(f"Entreprise #{i} : champ 'siren' manquant.")
 
        # On normalise le nom vers 'nom_entreprise'
        if "nom_entreprise" not in company:
            company["nom_entreprise"] = company.get("nom d'entreprise")
 
    return data
 
 
def enrich_company(company: dict) -> dict:
    """Prend {"siren", "nom_entreprise"} et retourne la fiche leadership complete."""
    siren = str(company["siren"]).strip()
    nom_fourni = company.get("nom_entreprise")
 
    # 1. La fiche officielle de l'entreprise
    api_data = fetch_company(siren)
 
    if api_data["erreur"]:
        return {
            "siren": siren,
            "nom_entreprise": nom_fourni,
            "age_entreprise": None,
            "dirigeants": [],
            "changements_ces_deux_dernieres_annees": "info non trouvée",
            "erreur": api_data["erreur"],
        }
 
    # 2. Les annonces legales (pour l'anciennete et les changements)
    bodacc = fetch_bodacc_annonces(siren)
    annonces = bodacc["annonces"]
 
    # 3. Les dirigeants legaux, personnes physiques uniquement
    dirigeants = []
    for d in extract_dirigeants(api_data["dirigeants"]):
        anciennete = estimate_tenure(d["nom_complet"], annonces)
        dirigeants.append(
            {
                "nom_complet": d["nom_complet"],
                "role": d["role"],
                "age": calculate_age(d["date_naissance"]),
                "anciennete_annees": anciennete["annees"],
                "anciennete_explication": anciennete["explication"],
            }
        )
 
    # 4. Les arrivees et departs des 2 dernieres annees
    changements = find_leadership_changes(annonces, FENETRE_RECENTE_ANNEES)
 
    return {
        "siren": siren,
        "nom_entreprise": api_data["nom"] or nom_fourni,
        "age_entreprise": calculate_company_age(api_data["date_creation"]),
        "dirigeants": dirigeants,
        "changements_ces_deux_dernieres_annees": changements,
        "erreur": bodacc["erreur"],
    }
 
 
def run_tool(companies: list[dict]) -> list[dict]:
    """Enrich each company and return the results."""
    return [enrich_company(company) for company in companies]

def run_tool_from_file(input_path: str, output_path: str):
    companies = load_input(input_path)
    results = run_tool(companies)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    return results
