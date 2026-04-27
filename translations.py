# -*- coding: utf-8 -*-
"""
BG translations for OzParts data.
Mappings used by sync_ozparts.py to localize category, group and product name
fields when generating the CloudCart feed.
"""

# ----- CATEGORIES (9) -----
CATEGORY_BG = {
    "SUSPENSION PARTS":   "Окачване",
    "SPRINGS AND SHOCKS": "Пружини и амортисьори",
    "BRAKES":             "Спирачки",
    "AIRBAGS":            "Въздушни възглавници",
    "BUSHES":             "Силентблокове",
    "SUSPENSION KITS":    "Комплекти окачване",
    "DRIVESHAFTS":        "Полуоски",
    "STEERING":           "Кормилно управление",
    "DRIVELINE":          "Трансмисия",
}

# ----- GROUPS / SUB-CATEGORIES (top frequency) -----
GROUP_BG = {
    "Front Shocks":                   "Преден амортисьор",
    "Rear Shock":                     "Заден амортисьор",
    "Front Shock":                    "Преден амортисьор",
    "Rear Shocks":                    "Заден амортисьор",
    "Front Shock Mounts":             "Тампон преден амортисьор",
    "Rear Shock Mounts":              "Тампон заден амортисьор",
    "Front Spring Low":               "Предна пружина (понижена)",
    "Front Spring Standard":          "Предна пружина (стандарт)",
    "Front Spring Raised":            "Предна пружина (повдигната)",
    "Rear Spring Low":                "Задна пружина (понижена)",
    "Rear Spring Standard":           "Задна пружина (стандарт)",
    "Rear Spring Raised":             "Задна пружина (повдигната)",
    "Front Brake Pads":               "Предни накладки",
    "Rear Brake Pads":                "Задни накладки",
    "Front Brake Rotors":             "Предни спирачни дискове",
    "Rear Brake Rotors":              "Задни спирачни дискове",
    "Front Anti-roll Bar Bushes":     "Тампон преден стабилизатор",
    "Rear Anti-roll Bar Bushes":      "Тампон заден стабилизатор",
    "Front Anti-roll Bar Links":      "Връзка преден стабилизатор",
    "Rear Anti-roll Bar Links":       "Връзка заден стабилизатор",
    "Front Lower Control Arm":        "Преден долен носач",
    "Rear Trailing Arm Lower":        "Заден долен носач",
    "Rear Lateral Arm Lower":         "Заден напречен носач",
    "Lower Ball Joint":               "Долен сачмен шарнир",
    "Upper Ball Joint":               "Горен сачмен шарнир",
    "Lower Inner Bush":               "Долен вътрешен силентблок",
    "Outer Tie Rod End":              "Външна щанга кормилен накрайник",
    "Inner Tie Rod End":              "Вътрешна щанга кормилен накрайник",
    "CV Shaft Assembly (Front)":      "Полуоска предна",
    "Outer Cv Boot (Front)":          "Външен маншон полуоска",
    "Front Bump Stop/Kit":            "Преден буфер / комплект",
    "Rear Bump Stop / Kit":           "Заден буфер / комплект",
    "Front Alignment Products":       "Предни алайнмент продукти",
    "Rear Alignment Products":        "Задни алайнмент продукти",
    "Rear Fixed Eye Bushes / Kits":   "Задни силентблокове на лист",
    "Idler Arm &/or Bush Kit":        "Спомагателна щанга / силентблок",
    "Radius / Brake Reaction Rod or Bushes": "Радиус щанги и силентблокове",
    "Coil Over Kits [Full Car]":      "Coilover комплекти (цяла кола)",
    "Brake Fluid":                    "Спирачна течност",
    "Airbag Controller Kits":         "Контролер на въздушни възглавници",
    "Rear Airbag":                    "Задна въздушна възглавница",
    "Front Airbag":                   "Предна въздушна възглавница",
    "Kits":                           "Комплекти",
}

# ----- KEYWORDS in product names (whole-word replace) -----
NAME_KEYWORDS_BG = {
    "Shock Absorber": "Амортисьор",
    "Coil Spring":    "Винтова пружина",
    "Leaf Spring":    "Листова пружина",
    "Brake Pads":     "Спирачни накладки",
    "Brake Rotor":    "Спирачен диск",
    "Brake Drum":     "Спирачен барабан",
    "Brake Shoes":    "Спирачни челюсти",
    "Brake Hose":     "Спирачен маркуч",
    "Ball Joint":     "Сачмен шарнир",
    "Tie Rod End":    "Кормилен накрайник",
    "Control Arm":    "Носач",
    "Bush Kit":       "Комплект силентблокове",
    "Bushing":        "Силентблок",
    "Bushes":         "Силентблокове",
    "Bush":           "Силентблок",
    "Sway Bar":       "Стабилизатор",
    "Anti-roll Bar":  "Стабилизатор",
    "Strut":          "Амортисьорна стойка",
    "Spring":         "Пружина",
    "Bump Stop":      "Буфер",
    "Air Bellow":     "Въздушна възглавница",
    "Bellows":        "Въздушна възглавница",
    "Mount":          "Тампон",
    "Suspension Kit": "Комплект окачване",
    "Lift Kit":       "Лифт комплект",
    "Heavy Duty":     "Усилен",
    "Air Suspension": "Въздушно окачване",
    "Coilover":       "Coilover",
    "Front":          "Преден",
    "Rear":           "Заден",
}


def translate_category(en):
    return CATEGORY_BG.get(en, en)


def translate_group(en):
    return GROUP_BG.get(en, en)


def translate_name(name):
    """Replace English keywords in a product name with BG equivalents.
    Order matters: longer phrases first so they take precedence."""
    if not name:
        return name
    out = name
    # Sort by length descending to match longest phrases first
    for en, bg in sorted(NAME_KEYWORDS_BG.items(), key=lambda x: -len(x[0])):
        out = out.replace(en, bg)
    return out
