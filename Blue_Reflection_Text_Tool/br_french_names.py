"""Hand-written French labels for the event speaker names (str_event_chara_name).

The fan release translated the "<trait> + <surname>" labels of the troubled
students almost word for word ("Mochizuki la beni-oui-oui", "Ichibangassen la
courroucee").  Only BLUE REFLECTION (2017) uses this naming scheme; the sequels
only have plain role labels, which are translated normally.

The surname stays in romaji and the trait becomes a short, natural French
nickname.  The school is all-girls, so the nicknames are feminine.

Text must stay font-safe: ASCII plus ``é`` (see ``br_french_cleanup``).
"""

from __future__ import annotations

from typing import Optional

# String_No -> French label.  Applied after cleanup, so these are final.
NAME_OVERRIDES: dict[str, str] = {
    # -- fixes for missing / misaligned entries ----------------------------
    "262163": "Membre de la réunion C",
    # -- troubled students (BR1 side quests) -------------------------------
    "262218": "Mochizuki la soumise",
    "262219": "Mitarai la fugueuse",
    "262220": "Ichibangassen la furieuse",
    "262221": "Kanzaki la distraite",
    "262222": "Sengoku l'insomniaque",
    "262223": "Hourai l'effrayante",
    "262224": "Hisamoto la terrorisée",
    "262225": "Maeno la léthargique",
    "262226": "Kashima la larmoyante",
    "262227": "Tanaka la voyante",
    "262228": "Miyazaki la survoltée",
    "262229": "Tokimoto la combative",
    "262230": "Toyoshima la désherbeuse",
    "262231": "Nose qui veut se concentrer",
    "262232": "Muratani l'épuisée",
    "262233": "Oe qui cherche le calme",
    "262234": "Fujisaki l'agacée",
    "262235": "Tachibana la hoqueteuse",
    "262236": "Kusunoki la triste",
    "262237": "Ohata la rieuse",
    "262238": "Aoki l'indécise",
    "262239": "Doumoto la réactive",
    "262240": "Mushanokouji la poisseuse",
    "262241": "Shiba la major",
    "262242": "Hagino la persévérante",
    "262243": "Niigaki la perfectionniste",
    "262244": "Mouri l'éplorée",
    "262245": "Toda la fiable ?",
    "262246": "Tsuiji la mélomane",
    "262247": "Hasebe la guetteuse",
    "262248": "Hori l'endeuillée",
    "262249": "Kawakami l'hésitante",
    "262250": "Muteki la hargneuse",
    "262251": "Ariake la parieuse",
    "262252": "Inukai la solitaire",
    "262253": "Hosaka la dealeuse de snacks",
    "262254": "Fukawa la geek",
    "262255": "Kishii l'excessive",
    "262256": "Hosokawa la dessinatrice",
    "262257": "Matsubara l'assidue",
    "262258": "Sasagawa l'efficace",
    "262259": "Takanawa l'anti-vacances",
    "262260": "Etou l'affligée",
    "262261": "Fujiwara la baleine",
    "262262": "Enoki la rouspeteuse",
    "262263": "Kobayakawa la déchirée",
    "262264": "Takanashi la désespérée",
    "262265": "Ishihara la comptable",
    "262266": "Minai l'intransigeante",
    "262267": "Momoi la future cheffe",
    "262268": "Nakao désolée pour les fleurs",
    "262269": "Watahara l'insatiable",
    "262270": "Nakatani la boutonneuse",
    "262272": "Yawa la tragédienne",
    "262274": "Fukuzawa qui bafouille",
    "262275": "Ikeno la désoeuvrée",
    "262276": "Masaoka cul sec",
    "262277": "Matsushima en révision",
    "262279": "Kagawa la fouineuse",
    "262281": "Yokono la vidéaste",
    "262282": "Kinoi la tacticienne",
    "262283": "Ninomiya la cheffe créative",
    "262284": "Takano la dévoreuse de livres",
    "262285": "Kanna la stressée",
    "262322": "Ohya la serviable",
    "262324": "Akutsu la prétentieuse",
    "262325": "Shimoda la rivale",
    "262326": "Mizushima de corvée",
    "262328": "Hama a fond dans sa jeunesse",
    "262329": "Kasuda la lycéenne épanouie",
    "262330": "Yoshizaki la studieuse",
    "262331": "Oda en mode par coeur",
    "262332": "Shigematsu soucieuse des cadettes",
    "262333": "Kawazoe la candidate",
    "262334": "Kodaira dévouée au club",
    "262335": "Shouji la franche",
    "262336": "Ukai sous le choc",
    "262337": "Ujie pensive",
    "262338": "Yanai la secrétaire ainée",
    "262340": "Kunimi la secrétaire cadette",
    "262342": "Sekino qui en demande trop",
    "262348": "Ochi du club Tout-Faire",
    "262350": "Serisawa la déléguée santé",
    "262352": "Sano l'obsédée de santé",
    "262353": "Andou la fausse malade",
    "262354": "Naitou la bibliothécaire",
    "262355": "Iinuma la fujoshi",
    "262357": "Suzuki la bosseuse ?",
    "262366": "Hara aux cours du soir",
    "262369": "Maruyama du club des rentre-chez-soi",
    "262370": "Ikoma du club des rentre-chez-soi",
    "262379": "Sumiyoshi du club de radio",
    "262380": "Kita sous les regards",
    "262381": "Nagumo qui observe",
    "262385": "Kiba soucieuse de l'avenir",
    "262387": "Kasai accro aux nouveautés",
    "262389": "Takagi consternée",
    "262391": "Sudou la moralisatrice",
    "262392": "Tsukuda sur les nerfs",
}

FONT_SAFE_EXTRA = {"\u00e9", "\u2026", "\u2019"}


def is_font_safe(text: str) -> bool:
    return all(ord(c) < 128 or c in FONT_SAFE_EXTRA for c in text)


def override_for(string_no: Optional[str]) -> Optional[str]:
    if string_no is None:
        return None
    return NAME_OVERRIDES.get(string_no)


if __name__ == "__main__":
    bad = {k: v for k, v in NAME_OVERRIDES.items() if not is_font_safe(v)}
    print(f"{len(NAME_OVERRIDES)} overrides, {len(bad)} not font-safe: {bad}")
