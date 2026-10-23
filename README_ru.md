# Gerber2MSLA

Засветка фоторезиста плат на MSLA-принтере (Anycubic Photon Mono X 6Ks): маска в точных
пикселях экрана становится файлом принтера, позже плата — из гербера.

ЖК-экран засвечивает ЦЕЛЫЕ пиксели, поэтому утилита работает в пикселях экрана — на этом
принтере 5760 x 3600, 34 мкм на пиксель по профилю UVtools/PrusaSlicer (это профиль, а не
проверенный паспорт). Файл принтера — однослойный `.px6s`; к принтеру ничего не отправляется,
лазера здесь нет.

Состояние: каркас пакета и тестовые маски, привязанные к пикселям. Конвертер (PNG → `.px6s`) —
следующий шаг плана `techdocs/handoff/deepseek/plan_2026_10_23_png2px6s.md`.

## Установка (для разработки)

```sh
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

## Тесты

```sh
.venv/bin/python -m pytest -q -rsf -p no:cacheprovider -n auto
.venv/bin/python -m pytest -q -rsf -p no:cacheprovider -n auto --reverse
```

English version: [README.md](README.md).
