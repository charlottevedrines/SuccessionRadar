"""Appels aux deux API gratuites (sans clé) : recherche-entreprises et BODACC.
 
Ce fichier ne fait QUE parler à Internet et transformer les reponses brutes
en petits dictionnaires propres. Il ne lit aucun fichier et n'en ecrit aucun.
"""
 
import json
import unicodedata
import urllib.request
from urllib.parse import urlencode
from datetime import date
 
# API 1 : la fiche officielle de l'entreprise (nom, date de creation, dirigeants)
API_ENTREPRISES = "https://recherche-entreprises.api.gouv.fr/search"
 
# API 2 : les annonces legales BODACC (creations, modifications, radiations)
API_BODACC = (
    "https://bodacc-datadila.opendatasoft.com/api/explore/v2.1"
    "/catalog/datasets/annonces-commerciales/records"
)
 
# Un changement est considere "recent" s'il date de moins de 2 ans.
FENETRE_RECENTE_ANNEES = 2
 
# Les roles qui nous interessent, du plus important au moins important.
ROLES_PRIORITAIRES = [
    "president",
    "president directeur general",
    "directeur general",
    "directeur general delegue",
    "directeur general unique",
    "gerant",
    "co gerant",
    "president du directoire",
    "membre du directoire",
]
 
# ---------------------------------------------------------------------------
# Petits utilitaires
# ---------------------------------------------------------------------------
 
def _get_json(url: str) -> dict:
    """Appelle une URL et retourne le JSON. Leve une exception si ca echoue."""
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read())
 
 
def _sans_accents(texte: str) -> str:
    """'Président' -> 'president'. Sert a comparer des mots sans se soucier
    des accents ni des majuscules."""
    texte = unicodedata.normalize("NFD", texte or "")
    texte = "".join(c for c in texte if unicodedata.category(c) != "Mn")
    return texte.lower().strip()
 
 
def _parse_date(texte: str | None) -> date | None:
    """Transforme '2019-04-12' ou '2019-04' ou '2019' en objet date."""
    if not texte:
        return None
    parts = str(texte).split("-")
    try:
        annee = int(parts[0])
        mois = int(parts[1]) if len(parts) > 1 else 1
        jour = int(parts[2][:2]) if len(parts) > 2 else 1
        return date(annee, mois, jour)
    except (ValueError, TypeError, IndexError):
        return None
 
 
def _annees_depuis(d: date | None) -> int | None:
    """Nombre d'annees entieres entre une date et aujourd'hui."""
    if not d:
        return None
    today = date.today()
    return today.year - d.year - ((today.month, today.day) < (d.month, d.day))
 
 
def calculate_age(date_naissance: str | None) -> int | None:
    """Age d'une personne a partir de sa date de naissance."""
    return _annees_depuis(_parse_date(date_naissance))
 
 
def calculate_company_age(date_creation: str | None) -> int | None:
    """Age de l'entreprise a partir de sa date de creation."""
    return _annees_depuis(_parse_date(date_creation))
 
 
# ---------------------------------------------------------------------------
# API 1 : recherche-entreprises.api.gouv.fr
# ---------------------------------------------------------------------------
 
def fetch_company(siren: str) -> dict:
    """Envoie le SIREN a l'API, retourne les infos brutes de l'entreprise."""
 
    params = urlencode({"q": siren, "per_page": "1", "minimal": "false"})
    url = f"{API_ENTREPRISES}?{params}"
 
    try:
        data = _get_json(url)
    except Exception as e:
        return {"nom": None, "date_creation": None, "dirigeants": [], "erreur": str(e)}
 
    results = data.get("results", [])
    match = [r for r in results if r.get("siren") == siren]
 
    if not match:
        return {
            "nom": None,
            "date_creation": None,
            "dirigeants": [],
            "erreur": "SIREN introuvable",
        }
 
    company = match[0]
    return {
        "nom": company.get("nom_raison_sociale") or company.get("nom_complet"),
        "date_creation": company.get("date_creation"),
        "dirigeants": company.get("dirigeants", []),
        "erreur": None,
    }
 
 
def _nom_complet(d: dict) -> str:
    """Reconstitue 'Prenom NOM' depuis un dirigeant de l'API."""
    prenom = d.get("prenoms") or d.get("prenom") or ""
    nom = d.get("nom") or d.get("nom_patronymique") or ""
    return f"{prenom} {nom}".strip()
 
 
def extract_dirigeants(dirigeants: list[dict]) -> list[dict]:
    """Garde uniquement les dirigeants PERSONNES PHYSIQUES, et les trie
    du role le plus important au moins important.
 
    Les personnes morales (une holding qui preside une filiale) sont ecartees :
    elles n'ont ni age ni anciennete individuelle.
    """
    retenus = []
 
    for d in dirigeants:
        # L'API marque les personnes morales avec type_dirigeant = "personne morale"
        type_dirigeant = _sans_accents(d.get("type_dirigeant") or "")
        if "morale" in type_dirigeant:
            continue
 
        nom = _nom_complet(d)
        if not nom:
            continue
 
        qualite = d.get("qualite") or ""
        qualite_simple = _sans_accents(qualite)
 
        # Rang = position dans ROLES_PRIORITAIRES (plus petit = plus important)
        rang = len(ROLES_PRIORITAIRES)
        for i, role in enumerate(ROLES_PRIORITAIRES):
            if role in qualite_simple:
                rang = i
                break
 
        retenus.append(
            {
                "nom_complet": nom,
                "role": qualite or None,
                "date_naissance": d.get("date_de_naissance"),
                "_rang": rang,
            }
        )
 
    retenus.sort(key=lambda d: d["_rang"])
    for d in retenus:
        del d["_rang"]
 
    return retenus
 
 
# ---------------------------------------------------------------------------
# API 2 : BODACC (annonces legales)
# ---------------------------------------------------------------------------
 
def fetch_bodacc_annonces(siren: str, limite: int = 100) -> dict:
    """Recupere les annonces BODACC d'une entreprise, de la plus recente
    a la plus ancienne.
 
    Retourne {"annonces": [...], "erreur": None} ou chaque annonce est
    {"date", "famille", "type", "descriptif"}.
    """
    # Le SIREN est range dans le champ 'registre' du BODACC. On essaie deux
    # ecritures de la requete : si la premiere est refusee, on tente la seconde.
    filtres = [f'registre LIKE "{siren}"', f'search(registre, "{siren}")']
 
    data = None
    derniere_erreur = None
 
    for filtre in filtres:
        params = urlencode(
            {
                "where": filtre,
                "order_by": "dateparution DESC",
                "limit": str(min(limite, 100)),
            }
        )
        try:
            data = _get_json(f"{API_BODACC}?{params}")
            break
        except Exception as e:
            derniere_erreur = e
 
    if data is None:
        return {"annonces": [], "erreur": f"BODACC indisponible : {derniere_erreur}"}
 
    annonces = []
    for enregistrement in data.get("results", []):
        annonces.append(
            {
                "date": enregistrement.get("dateparution"),
                "famille": enregistrement.get("familleavis_lib")
                or enregistrement.get("familleavis"),
                "type": enregistrement.get("typeavis_lib")
                or enregistrement.get("typeavis"),
                "descriptif": _descriptif(enregistrement),
            }
        )
 
    return {"annonces": annonces, "erreur": None}
 
 
def _descriptif(enregistrement: dict) -> str:
    """Le texte lisible d'une annonce se cache dans un champ JSON
    'modificationsgenerales'. On en extrait la phrase descriptive."""
    brut = enregistrement.get("modificationsgenerales")
 
    if isinstance(brut, str):
        try:
            brut = json.loads(brut)
        except (ValueError, TypeError):
            return brut
 
    if isinstance(brut, dict):
        return brut.get("descriptif") or ""
 
    return ""
 
 
# ---------------------------------------------------------------------------
# Lecture des annonces : changements de dirigeants et anciennete
# ---------------------------------------------------------------------------
 
# Mots qui, dans une annonce, signalent le DEPART d'une personne.
MOTS_DEPART = ["ancien", "partant", "sortant", "demission", "n'est plus", "cessation"]
 
# Mots qui signalent qu'on parle bien de dirigeants.
MOTS_DIRIGEANT = ROLES_PRIORITAIRES + ["administration", "dirigeant", "directeur"]
 
 
def find_leadership_changes(annonces: list[dict], fenetre_annees: int = FENETRE_RECENTE_ANNEES) -> list[str] | str:
    """Repere, dans les annonces BODACC, les changements de dirigeants des
    N dernieres annees.
 
    Retourne une liste de phrases du type
    "2025-06-02 | arrivée | Président : DUPONT Jean",
    ou "info non trouvée" s'il n'y a aucun changement.
    """
    changements = []
 
    for annonce in annonces:
        d = _parse_date(annonce.get("date"))
 
        # Pas de date, ou trop vieux : on ignore
        if not d or _annees_depuis(d) >= fenetre_annees:
            continue
 
        descriptif = annonce.get("descriptif") or ""
 
        # L'annonce parle-t-elle de dirigeants ?
        if not any(mot in _sans_accents(descriptif) for mot in MOTS_DIRIGEANT):
            continue
 
        # Une annonce liste plusieurs personnes separees par des ';'
        for segment in descriptif.split(";"):
            segment = segment.strip()
            segment_simple = _sans_accents(segment)
 
            if not any(mot in segment_simple for mot in MOTS_DIRIGEANT):
                continue
 
            # Un nom est publie quand il y a "Role : NOM Prenom" dans le texte.
            # Sinon l'annonce dit juste "Modification survenue sur l'administration."
            if ":" not in segment:
                phrase = f"{d.isoformat()} | changement dans la direction | noms non publiés au BODACC"
            else:
                sens = "départ" if any(m in segment_simple for m in MOTS_DEPART) else "arrivée"
                # On enleve l'introduction "Modification survenue sur l'administration."
                if "." in segment.split(":")[0]:
                    segment = segment.split(".", 1)[1].strip()
                phrase = f"{d.isoformat()} | {sens} | {segment}"
 
            if phrase not in changements:
                changements.append(phrase)
 
    return changements if changements else "info non trouvée"
 
 
def estimate_tenure(nom_complet: str, annonces: list[dict]) -> dict:
    """Estime depuis combien de temps une personne est dans l'entreprise.
 
    L'API gouv ne donne PAS la date de nomination. On cherche donc la plus
    ancienne annonce BODACC qui cite cette personne. Si aucune ne la cite,
    on laisse vide plutot que d'inventer un chiffre.
    """
    # On compare sur le nom et le prenom, sans accents ni majuscules.
    morceaux = [m for m in _sans_accents(nom_complet).split() if len(m) > 2]
 
    dates_citant_la_personne = []
    for annonce in annonces:
        texte = _sans_accents(annonce.get("descriptif") or "")
        if morceaux and all(m in texte for m in morceaux):
            d = _parse_date(annonce.get("date"))
            if d:
                dates_citant_la_personne.append(d)
 
    if dates_citant_la_personne:
        premiere = min(dates_citant_la_personne)
        return {
            "annees": _annees_depuis(premiere),
            "explication": (
                "Date exacte de nomination non trouvée ; estimée à partir de la "
                f"première annonce BODACC qui cite cette personne ({premiere.isoformat()})."
            ),
        }
 
    return {
        "annees": None,
        "explication": "info non trouvée : aucune annonce BODACC ne cite cette personne.",
    }
