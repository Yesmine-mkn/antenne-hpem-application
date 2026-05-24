from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Any, Dict, List, Tuple

C0 = 299792458.0
Z0 = 376.730313668
MU0 = 4.0 * math.pi * 1e-7
SIGMA_ALUMINUM = 3.5e7
AIR_BREAKDOWN_V_PER_M = 3.0e6


@dataclass(frozen=True)
class WaveguidePreset:
    name: str
    a_mm: float
    b_mm: float
    recommended_min_ghz: float
    recommended_max_ghz: float
    comment: str = ""

    @property
    def a_m(self) -> float:
        return self.a_mm * 1e-3

    @property
    def b_m(self) -> float:
        return self.b_mm * 1e-3

    @property
    def fc_te10_ghz(self) -> float:
        return C0 / (2.0 * self.a_m) / 1e9

    @property
    def fc_te20_ghz(self) -> float:
        return C0 / self.a_m / 1e9

    @property
    def fc_te01_ghz(self) -> float:
        return C0 / (2.0 * self.b_m) / 1e9

    @property
    def upper_mode_ghz(self) -> float:
        return min(self.fc_te20_ghz, self.fc_te01_ghz)


WAVEGUIDES: Dict[str, WaveguidePreset] = {
    "WR430": WaveguidePreset(
        name="WR430",
        a_mm=109.22,
        b_mm=54.61,
        recommended_min_ghz=1.72,
        recommended_max_ghz=2.60,
        comment="Guide large pour le bas de la bande S et les fortes puissances.",
    ),
    "WR340": WaveguidePreset(
        name="WR340",
        a_mm=86.36,
        b_mm=43.18,
        recommended_min_ghz=2.20,
        recommended_max_ghz=3.30,
        comment="Guide S-band courant autour de 2.45 GHz.",
    ),
    "WR284": WaveguidePreset(
        name="WR284",
        a_mm=72.136,
        b_mm=34.036,
        recommended_min_ghz=2.60,
        recommended_max_ghz=3.95,
        comment="Guide adapte au haut de la bande S.",
    ),
}


@dataclass
class AntennaParams:
    f_center_ghz: float = 2.45
    f_min_ghz: float = 2.20
    f_max_ghz: float = 3.30
    guide_type: str = "WR340"
    horn_length_mm: float = 300.0
    aperture_width_mm: float = 300.0
    aperture_height_mm: float = 250.0
    aluminum_thickness_mm: float = 2.0
    aperture_efficiency: float = 0.60
    peak_power_mw: float = 1.0


@dataclass
class FabricationDefects:
    roughness_um: float = 6.0
    tolerance_mm: float = 0.5
    weld_count: float = 3.0
    alignment_error_mm: float = 1.0
    oxidation_level: float = 1.0
    mastic_present: bool = False
    mastic_severity: float = 0.0


def waveguide_names() -> List[str]:
    return list(WAVEGUIDES.keys())


def auto_select_waveguide(f_center_ghz: float, f_min_ghz: float | None = None, f_max_ghz: float | None = None) -> tuple[str, str]:
    guides = list(WAVEGUIDES.values())
    if f_min_ghz is None:
        f_min_ghz = f_center_ghz
    if f_max_ghz is None:
        f_max_ghz = f_center_ghz

    exact_band = [g for g in guides if g.recommended_min_ghz <= f_min_ghz and f_max_ghz <= g.recommended_max_ghz]
    if exact_band:
        best = min(exact_band, key=lambda g: abs((g.recommended_min_ghz + g.recommended_max_ghz) / 2.0 - f_center_ghz))
        return best.name, f"Guide conseille: {best.name}. Il couvre toute la bande demandee {f_min_ghz:.2f}-{f_max_ghz:.2f} GHz dans sa plage recommandee."

    exact_center = [g for g in guides if g.recommended_min_ghz <= f_center_ghz <= g.recommended_max_ghz]
    if exact_center:
        best = min(exact_center, key=lambda g: abs((g.recommended_min_ghz + g.recommended_max_ghz) / 2.0 - f_center_ghz))
        return best.name, f"Guide conseille: {best.name}. Il convient a la frequence centrale {f_center_ghz:.2f} GHz, mais la bande complete demandee depasse sa plage recommandee."

    best = min(guides, key=lambda g: abs((g.recommended_min_ghz + g.recommended_max_ghz) / 2.0 - f_center_ghz))
    return best.name, f"Aucun guide ne couvre parfaitement la bande demandee. Le plus proche autour de {f_center_ghz:.2f} GHz est {best.name}."


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def db10(linear: float) -> float:
    if linear <= 0:
        return float("-inf")
    return 10.0 * math.log10(linear)


def lin10(db_value: float) -> float:
    return 10.0 ** (db_value / 10.0)


def fmt(value: float, digits: int = 2) -> str:
    return f"{value:.{digits}f}"


def skin_depth_aluminum_um(f_ghz: float, sigma: float = SIGMA_ALUMINUM) -> float:
    omega = 2.0 * math.pi * f_ghz * 1e9
    delta_m = math.sqrt(2.0 / (omega * MU0 * sigma))
    return delta_m * 1e6


def normalized_design(
    f_center_ghz: float,
    desired_gain_dbi: float,
    aperture_efficiency: float = 0.5,
    aspect_ratio_ab: float = 1.5,
) -> Dict[str, float]:
    f_hz = max(f_center_ghz, 1e-9) * 1e9
    wavelength_m = C0 / f_hz
    eta = clamp(aperture_efficiency, 0.05, 0.95)
    ratio = max(aspect_ratio_ab, 0.1)
    gain_linear = lin10(desired_gain_dbi)
    area_m2 = gain_linear * (wavelength_m ** 2) / (4.0 * math.pi * eta)
    a_m = math.sqrt(area_m2 * ratio)
    b_m = math.sqrt(area_m2 / ratio)
    r_h_m = (a_m ** 2) / (3.0 * wavelength_m)
    r_e_m = (b_m ** 2) / (2.0 * wavelength_m)
    l_suggested_m = max(r_h_m, r_e_m)
    return {
        "gain_linear": gain_linear,
        "wavelength_mm": wavelength_m * 1e3,
        "aperture_area_m2": area_m2,
        "aperture_width_mm": a_m * 1e3,
        "aperture_height_mm": b_m * 1e3,
        "r_h_mm": r_h_m * 1e3,
        "r_e_mm": r_e_m * 1e3,
        "horn_length_suggested_mm": l_suggested_m * 1e3,
        "aspect_ratio_ab": ratio,
        "aperture_efficiency": eta,
        "desired_gain_dbi": desired_gain_dbi,
    }


def mode_status(params: AntennaParams) -> Tuple[str, List[str]]:
    guide = WAVEGUIDES[params.guide_type]
    warnings: List[str] = []

    if params.f_min_ghz <= guide.fc_te10_ghz:
        warnings.append("La borne basse est sous ou trop proche de la coupure TE10.")
    if params.f_max_ghz >= guide.upper_mode_ghz:
        warnings.append("La borne haute est proche d'un mode superieur: risque de modes parasites.")
    if not (guide.recommended_min_ghz <= params.f_center_ghz <= guide.recommended_max_ghz):
        warnings.append("La frequence centrale est hors de la plage recommandee du guide choisi.")

    if warnings:
        return "A verifier", warnings
    return "TE10 dominant valide", warnings


def compute_theoretical(params: AntennaParams) -> Dict[str, Any]:
    guide = WAVEGUIDES[params.guide_type]
    f_hz = max(params.f_center_ghz, 1e-9) * 1e9
    wavelength_m = C0 / f_hz

    aperture_width_m = max(params.aperture_width_mm * 1e-3, 1e-9)
    aperture_height_m = max(params.aperture_height_mm * 1e-3, 1e-9)
    aperture_area_m2 = aperture_width_m * aperture_height_m

    directivity_linear = 4.0 * math.pi * aperture_area_m2 / (wavelength_m ** 2)
    efficiency = clamp(params.aperture_efficiency, 0.05, 0.95)
    gain_linear = efficiency * directivity_linear
    effective_aperture_m2 = efficiency * aperture_area_m2

    hpbw_h_deg = clamp(67.0 * wavelength_m / aperture_width_m, 1.0, 180.0)
    hpbw_e_deg = clamp(56.0 * wavelength_m / aperture_height_m, 1.0, 180.0)

    status, warnings = mode_status(params)

    aperture_ratio_w = params.aperture_width_mm / guide.a_mm
    aperture_ratio_h = params.aperture_height_mm / guide.b_mm
    min_aperture_ratio = min(aperture_ratio_w, aperture_ratio_h)
    length_lambda = params.horn_length_mm * 1e-3 / wavelength_m

    base_s11_db = -22.0
    if min_aperture_ratio < 1.8:
        base_s11_db += (1.8 - min_aperture_ratio) * 4.0
    if length_lambda < 1.3:
        base_s11_db += (1.3 - length_lambda) * 3.5
    if status != "TE10 dominant valide":
        base_s11_db += 4.0
    base_s11_db = clamp(base_s11_db, -28.0, -9.0)

    return {
        "guide": asdict(guide),
        "f_center_ghz": params.f_center_ghz,
        "f_min_ghz": params.f_min_ghz,
        "f_max_ghz": params.f_max_ghz,
        "wavelength_mm": wavelength_m * 1e3,
        "fc_te10_ghz": guide.fc_te10_ghz,
        "upper_mode_ghz": guide.upper_mode_ghz,
        "mode_status": status,
        "warnings": warnings,
        "aperture_area_m2": aperture_area_m2,
        "directivity_dbi": db10(directivity_linear),
        "gain_dbi": db10(gain_linear),
        "effective_aperture_m2": effective_aperture_m2,
        "hpbw_h_deg": hpbw_h_deg,
        "hpbw_e_deg": hpbw_e_deg,
        "base_s11_db": base_s11_db,
        "length_lambda": length_lambda,
        "aperture_ratio_w": aperture_ratio_w,
        "aperture_ratio_h": aperture_ratio_h,
    }


def compute_defect_penalties(params: AntennaParams, defects: FabricationDefects, theoretical: Dict[str, Any]) -> Dict[str, Any]:
    guide = WAVEGUIDES[params.guide_type]
    delta_um = skin_depth_aluminum_um(params.f_center_ghz)
    roughness_ratio = defects.roughness_um / max(delta_um, 1e-6)

    roughness_loss_db = clamp(0.06 * roughness_ratio + 0.18 * math.log1p(roughness_ratio), 0.0, 3.0)
    weld_loss_db = clamp(0.075 * defects.weld_count * (1.0 + clamp(roughness_ratio / 10.0, 0.0, 0.8)), 0.0, 2.5)

    dimensional_relative_error = defects.tolerance_mm / max(guide.a_mm, 1e-9)
    frequency_shift_mhz = params.f_center_ghz * 1e3 * dimensional_relative_error
    dimensional_loss_db = clamp(0.16 * ((defects.tolerance_mm / 0.20) ** 1.10), 0.0, 2.5)

    alignment_reference_mm = max(0.01 * guide.a_mm, 0.75)
    alignment_norm = defects.alignment_error_mm / alignment_reference_mm
    alignment_loss_db = clamp(0.28 * (alignment_norm ** 1.25), 0.0, 3.0)

    oxidation_loss_db = clamp(0.10 * defects.oxidation_level, 0.0, 1.5)
    mastic_loss_db = 0.0
    if defects.mastic_present:
        mastic_loss_db = clamp(0.35 + 0.15 * defects.mastic_severity, 0.0, 2.0)

    total_loss_db = roughness_loss_db + weld_loss_db + dimensional_loss_db + alignment_loss_db + oxidation_loss_db + mastic_loss_db

    s11_degradation_db = 4.0 * (
        0.95 * roughness_loss_db
        + 1.10 * weld_loss_db
        + 1.75 * alignment_loss_db
        + 0.90 * dimensional_loss_db
        + 0.65 * oxidation_loss_db
        + 1.50 * mastic_loss_db
    )
    s11_db = clamp(theoretical["base_s11_db"] + s11_degradation_db, -28.0, -3.0)

    return {
        "skin_depth_um": delta_um,
        "roughness_ratio_skin_depth": roughness_ratio,
        "roughness_loss_db": roughness_loss_db,
        "weld_loss_db": weld_loss_db,
        "dimensional_loss_db": dimensional_loss_db,
        "alignment_loss_db": alignment_loss_db,
        "oxidation_loss_db": oxidation_loss_db,
        "mastic_loss_db": mastic_loss_db,
        "total_loss_db": total_loss_db,
        "estimated_frequency_shift_mhz": frequency_shift_mhz,
        "s11_db": s11_db,
    }


def compute_hpem(params: AntennaParams, defects: FabricationDefects, penalties: Dict[str, Any]) -> Dict[str, Any]:
    guide = WAVEGUIDES[params.guide_type]
    throat_area_m2 = max(guide.a_m * guide.b_m, 1e-9)
    aperture_area_m2 = max(params.aperture_width_mm * 1e-3 * params.aperture_height_mm * 1e-3, 1e-9)
    power_w = max(params.peak_power_mw, 0.0) * 1e6

    concentration_factor = 1.0
    concentration_factor += 0.035 * min(defects.weld_count, 8.0)
    concentration_factor += 0.020 * min(penalties["roughness_ratio_skin_depth"], 15.0)
    concentration_factor += 0.055 * min(defects.alignment_error_mm, 5.0)
    concentration_factor += 0.040 * min(defects.oxidation_level, 5.0)
    if defects.mastic_present:
        concentration_factor += 0.15 + 0.03 * min(defects.mastic_severity, 5.0)

    e_peak_throat_vpm = math.sqrt(2.0 * Z0 * power_w / throat_area_m2) * concentration_factor
    e_peak_aperture_vpm = math.sqrt(2.0 * Z0 * power_w / aperture_area_m2) * concentration_factor
    breakdown_margin = AIR_BREAKDOWN_V_PER_M / max(e_peak_throat_vpm, 1.0)

    roughness_score_penalty = clamp(3.2 * (penalties["roughness_ratio_skin_depth"] ** 0.72), 0.0, 25.0)
    weld_score_penalty = clamp(2.6 * defects.weld_count, 0.0, 20.0)
    alignment_score_penalty = clamp(5.0 * defects.alignment_error_mm, 0.0, 18.0)
    oxidation_score_penalty = clamp(3.6 * defects.oxidation_level, 0.0, 18.0)
    mastic_score_penalty = 0.0
    if defects.mastic_present:
        mastic_score_penalty = clamp(7.0 + 2.0 * defects.mastic_severity, 0.0, 18.0)

    thickness_score_penalty = 0.0
    if params.aluminum_thickness_mm < 1.5:
        thickness_score_penalty = clamp((1.5 - params.aluminum_thickness_mm) * 8.0, 0.0, 12.0)

    field_ratio = e_peak_throat_vpm / AIR_BREAKDOWN_V_PER_M
    field_score_penalty = clamp((field_ratio - 0.35) * 32.0, 0.0, 30.0)

    total_penalty = roughness_score_penalty + weld_score_penalty + alignment_score_penalty + oxidation_score_penalty + mastic_score_penalty + thickness_score_penalty + field_score_penalty
    score_hpem = clamp(100.0 - total_penalty, 0.0, 100.0)

    if breakdown_margin < 1.2:
        risk = "Eleve"
    elif breakdown_margin < 2.0:
        risk = "Moyen"
    else:
        risk = "Faible"

    critical_zones = [
        "transition guide-cornet",
        "aretes de l'ouverture",
        "soudures internes et reprises de matiere",
    ]
    if defects.mastic_present:
        critical_zones.append("zones contenant du mastic ou une matiere dielectrique")
    if defects.oxidation_level >= 2:
        critical_zones.append("zones oxydees ou mal protegees")

    return {
        "concentration_factor": concentration_factor,
        "e_peak_throat_kv_per_m": e_peak_throat_vpm / 1e3,
        "e_peak_aperture_kv_per_m": e_peak_aperture_vpm / 1e3,
        "breakdown_margin_air": breakdown_margin,
        "breakdown_risk": risk,
        "critical_zones": critical_zones,
        "score_hpem": score_hpem,
        "score_penalties": {
            "rugosite": roughness_score_penalty,
            "soudures": weld_score_penalty,
            "alignement": alignment_score_penalty,
            "oxydation": oxidation_score_penalty,
            "mastic": mastic_score_penalty,
            "epaisseur": thickness_score_penalty,
            "champ electrique": field_score_penalty,
        },
    }


def corrected_defects(defects: FabricationDefects) -> FabricationDefects:
    return FabricationDefects(
        roughness_um=max(0.6, defects.roughness_um * 0.35),
        tolerance_mm=defects.tolerance_mm * 0.80,
        weld_count=max(0.0, defects.weld_count * 0.70),
        alignment_error_mm=defects.alignment_error_mm * 0.55,
        oxidation_level=defects.oxidation_level * 0.35,
        mastic_present=False,
        mastic_severity=0.0,
    )


def calculate_all(params: AntennaParams, defects: FabricationDefects) -> Dict[str, Any]:
    theoretical = compute_theoretical(params)
    fabricated_penalties = compute_defect_penalties(params, defects, theoretical)
    fabricated_hpem = compute_hpem(params, defects, fabricated_penalties)
    fabricated_gain = theoretical["gain_dbi"] - fabricated_penalties["total_loss_db"]

    improved_defects = corrected_defects(defects)
    corrected_penalties = compute_defect_penalties(params, improved_defects, theoretical)
    corrected_hpem = compute_hpem(params, improved_defects, corrected_penalties)
    corrected_gain = theoretical["gain_dbi"] - corrected_penalties["total_loss_db"]

    comparison = [
        {
            "Cas": "Theorique",
            "Gain dBi": theoretical["gain_dbi"],
            "S11 dB": theoretical["base_s11_db"],
            "Score HPEM %": 95.0 if theoretical["mode_status"] == "TE10 dominant valide" else 78.0,
        },
        {
            "Cas": "Fabrique",
            "Gain dBi": fabricated_gain,
            "S11 dB": fabricated_penalties["s11_db"],
            "Score HPEM %": fabricated_hpem["score_hpem"],
        },
        {
            "Cas": "Apres finition",
            "Gain dBi": corrected_gain,
            "S11 dB": corrected_penalties["s11_db"],
            "Score HPEM %": corrected_hpem["score_hpem"],
        },
    ]

    return {
        "params": asdict(params),
        "defects": asdict(defects),
        "theoretical": theoretical,
        "fabricated": {
            "gain_dbi": fabricated_gain,
            "penalties": fabricated_penalties,
            "hpem": fabricated_hpem,
        },
        "corrected_defects": asdict(improved_defects),
        "corrected": {
            "gain_dbi": corrected_gain,
            "penalties": corrected_penalties,
            "hpem": corrected_hpem,
        },
        "comparison": comparison,
    }


def defect_effect_table() -> List[Dict[str, str]]:
    return [
        {"Defaut": "Rugosite interne", "Effet RF": "augmentation des pertes de surface et echauffement local"},
        {"Defaut": "Soudures irregulieres", "Effet RF": "reflexions locales, concentration du champ et pertes"},
        {"Defaut": "Erreur dimensionnelle", "Effet RF": "decalage de frequence et modification du diagramme"},
        {"Defaut": "Desalignement guide-cornet", "Effet RF": "degradation du S11 et excitation de modes indesirables"},
        {"Defaut": "Oxydation", "Effet RF": "pertes supplementaires par resistance de surface"},
        {"Defaut": "Mastic interne", "Effet RF": "perturbation dielectrique, echauffement et risque de claquage"},
    ]


def generate_recommendations(results: Dict[str, Any]) -> List[str]:
    recs: List[str] = []
    defects = results["defects"]
    params = results["params"]
    theory = results["theoretical"]
    fabricated = results["fabricated"]
    corrected = results["corrected"]
    penalties = fabricated["penalties"]
    hpem = fabricated["hpem"]

    if theory["mode_status"] != "TE10 dominant valide":
        recs.append("Revoir le choix du guide ou la bande de frequence: la propagation TE10 dominante n'est pas garantie sur toute la bande.")

    if penalties["roughness_loss_db"] >= 0.35 or defects["roughness_um"] > 5:
        recs.append("Les pertes sont principalement liees a la rugosite interne. Une finition par poncage puis polissage est recommandee, surtout au niveau de la transition guide-cornet.")

    if penalties["weld_loss_db"] >= 0.25 or defects["weld_count"] >= 3:
        recs.append("Reduire le nombre de soudures internes par pliage ou placer les cordons hors des zones de courant RF intense. La continuite des courants de surface sera amelioree.")

    if penalties["alignment_loss_db"] >= 0.20 or defects["alignment_error_mm"] >= 0.8:
        recs.append("Ameliorer l'alignement guide-cornet avec un gabarit mecanique, des piges de centrage ou une bride plus rigide afin de diminuer le S11.")

    if penalties["dimensional_loss_db"] >= 0.35 or defects["tolerance_mm"] >= 0.5:
        recs.append("Controler les dimensions reelles de l'ouverture et de la gorge: les erreurs dimensionnelles peuvent decaler la frequence optimale. Un controle au pied a coulisse ou au scan 3D est utile.")

    if defects["oxidation_level"] >= 2:
        recs.append("Nettoyer les surfaces internes et appliquer une protection compatible RF. L'oxydation augmente la resistance de surface et reduit la tenue en puissance.")

    if defects["mastic_present"]:
        recs.append("Eviter le mastic ou les materiaux dielectriques dans le volume RF. Preferer une etancheite externe ou une reprise metallique conductrice.")

    if params["aluminum_thickness_mm"] < 1.5:
        recs.append("Augmenter l'epaisseur de l'aluminium ou rigidifier la structure pour limiter les deformations et mieux tenir les fortes contraintes HPEM.")

    if hpem["breakdown_risk"] == "Eleve":
        recs.append("Le risque de decharge electrique est eleve. Adoucir les aretes, soigner les transitions et reduire les discontinuites de surface avant les essais HPEM.")
    elif hpem["breakdown_risk"] == "Moyen":
        recs.append("Verifier les zones critiques avant essai HPEM: gorge, soudures internes et aretes de l'ouverture.")

    if params["horn_length_mm"] < 0.7 * max(params["aperture_width_mm"], params["aperture_height_mm"]):
        recs.append("Le cornet semble relativement court. Une augmentation moderee de la longueur peut aider a lisser la transition de phase et a ameliorer le diagramme de rayonnement.")

    if theory["hpbw_h_deg"] > 38 or theory["hpbw_e_deg"] > 38:
        recs.append("Le faisceau reste assez large. Si un faisceau plus directif est recherche, augmenter l'ouverture A x B ou recalculer les dimensions a partir d'un gain cible plus eleve.")

    if abs(theory["hpbw_h_deg"] - theory["hpbw_e_deg"]) > 12:
        recs.append("Les largeurs de faisceau des plans H et E sont assez differentes. Ajuster le rapport A/B peut equilibrer le diagramme de rayonnement entre les deux plans.")

    if abs(fabricated["gain_dbi"] - corrected["gain_dbi"]) >= 0.5:
        recs.append("La finition apporte un gain appreciable dans le modele. Il est pertinent de prevoir un etat 'avant/apres finition' dans les essais experimentaux.")

    recs.append("Confirmer les performances par une mesure VNA du S11 sur la bande complete, puis relever le diagramme de rayonnement en chambre anechoique ou par rotation angulaire si le banc le permet.")

    if defects["weld_count"] <= 1 and defects["roughness_um"] <= 3 and defects["alignment_error_mm"] <= 0.4:
        recs.append("La fabrication est deja propre. Un polissage fin et un controle dimensionnel final devraient suffire pour approcher l'etat theorique.")

    # Deduplicate while preserving order
    out: List[str] = []
    seen = set()
    for rec in recs:
        if rec not in seen:
            out.append(rec)
            seen.add(rec)

    if not out:
        out.append("Aucune alerte majeure. Confirmer toutefois les resultats par mesure VNA et, si possible, par simulation EM 3D.")

    return out
