# OzParts → CloudCart auto-sync

Автоматичен sync на продуктовия каталог от OzParts (Pedders, DBA, Hawk, ACL Race, XtremeClutch) към autofixparts24.com (CloudCart).

Стартира автоматично всеки 6 часа чрез GitHub Actions, регенерира XML feed-а и го качва на GitHub Pages, откъдето CloudCart го дърпа автоматично.

---

## Setup инструкции (еднократно, ~5 минути)

### Стъпка 1 — Създай нов празен repo на GitHub

1. Отвори https://github.com/new
2. **Repository name:** `ozparts-sync` (или каквото предпочиташ)
3. **Visibility:** **Public** (важно — GitHub Pages иска public repo за безплатен план)
4. ❌ **Не** избирай "Add a README file"
5. Натисни **Create repository**

### Стъпка 2 — Качи файловете

В новия празен repo ще видиш страница с инструкции. Натисни **uploading an existing file** (или drag-drop в страницата).

Качи следните файлове и папки от тази директория (`ozparts-sync/`):

```
.github/
  └── workflows/
      └── sync.yml
docs/             (празна папка — ще се напълни автоматично)
sync_ozparts.py
requirements.txt
README.md
.gitignore
```

> **Tip:** Drag-drop-ваш ЦЯЛАТА `ozparts-sync` папка в browser-а — GitHub приема цялото съдържание наведнъж.

Натисни **Commit changes** най-долу.

### Стъпка 3 — GitHub Actions ще пусне автоматично

След като push-неш файловете, отиди в раздел **Actions** на repo-то.

Ще видиш първия run на "OzParts → CloudCart sync" започнал автоматично. Изчакай ~3-5 минути да приключи.

Когато видиш зелена ✅ отметка, проверката е минала. Ще е commit-нал автоматично:
- `docs/cloudcart_feed.xml` — XML feed-ът за CloudCart
- `docs/vehicle_index.json` — index за vehicle filter widget-а

### Стъпка 4 — Включи GitHub Pages

1. Settings → Pages
2. **Source:** Deploy from a branch
3. **Branch:** `main` / `/docs`
4. **Save**

След ~1 минута GitHub ще ти даде URL:
```
https://<твой-username>.github.io/ozparts-sync/
```

Тестово отвори `https://<твой-username>.github.io/ozparts-sync/cloudcart_feed.xml` в browser — трябва да видиш XML файла.

### Стъпка 5 — Свържи с CloudCart

Връщаш се в CloudCart admin → Импортиране на продукти → "Приложение за синхронизация на продукти чрез XML" → **Стъпка 1**:

| Поле | Стойност |
|---|---|
| Име на задачата | `OzParts автоматичен sync` |
| URL на XML | `https://<твой-username>.github.io/ozparts-sync/cloudcart_feed.xml` |
| XML таг на продукта | `product` |
| Редове | `100` |

Натисни **Валидиране на XML и продължаване** → следваш wizard-а до края.

В **Стъпка 2** mappваш полетата както е описано в инструкциите.

---

## Конфигурация на цените

Всички ценови параметри са в `.github/workflows/sync.yml` (env: секцията). За да смениш марж/транспорт, редактираш един ред в YAML и push-ваш — Actions автоматично ще пусне нов run.

| Променлива | Стойност | Какво прави |
|---|---|---|
| `MARGIN_PCT` | `30` | % печалба върху landed cost |
| `SUPPLIER_DISCOUNT` | `20` | % отстъпка от RRP (твоя cost) |
| `VAT_PCT` | `20` | % ДДС |
| `PRICE_ROUND` | `whole` | закръгляне (whole / 0.95 / 0.99) |
| `SHIPPING_PER_KG` | `2.00` | € транспорт на кг |
| `SHIPPING_MIN` | `1.50` | минимум транспорт на брой |
| `SHIPPING_FALLBACK` | `3.00` | транспорт ако няма weight |

## Ръчен start на sync-а

Ако искаш да пуснеш sync извънредно (примерно при ценова промяна):

1. Actions → OzParts → CloudCart sync
2. Натисни **Run workflow** → branch: main → **Run workflow**

---

## Структура на файловете

- `sync_ozparts.py` — главният Python script
- `.github/workflows/sync.yml` — GitHub Actions schedule (cron 6h)
- `requirements.txt` — Python зависимости
- `docs/cloudcart_feed.xml` — генериран от sync-а (CloudCart import)
- `docs/vehicle_index.json` — генериран от sync-а (vehicle filter widget)
