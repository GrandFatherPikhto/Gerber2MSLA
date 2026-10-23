# Что лежит в чём (экран / фигура / ширина / файл принтера)

Gerber2MSLA, 23.10.2026: `Screen`, `Figure` и `Width` — код П4 плана `png2px6s`; `px6s` — план П2/П3.
Когда появится код `px6s` — заменить пометки на `файл:строка`, как в Gerber2LDI.

---

## Экран и фигура — `gerber2msla/masks.py` (П4)

```
Screen                             — неизменяемый (masks.py:50)
  width_px: int                    — ширина экрана в пикселях (5760 у X6Ks)
  height_px: int                   — высота экрана в пикселях (3600)
  pixel_x_um: float                — размер одного пикселя по X (34.0)
  pixel_y_um: float                — по Y; может отличаться (неквадратный пиксель)
  pixel_x_mm / pixel_y_mm          — те же в мм
  mm_x(px) / mm_y(px)              — пиксели → мм по оси

Figure                             — неизменяемый (masks.py:74)
  pixels: np.ndarray (uint8)       — рисунок в своих пикселях: только 0 и 255
  report: tuple[str, ...]          — строки отчёта, которые к нему относятся
  width_px / height_px             — из формы массива
```

Отчёт едет вместе с фигурой намеренно: маска, которая врёт про свои числа, хуже отсутствующей, поэтому
запрошенные и ФАКТИЧЕСКИЕ ширины пишутся и в stdout, и в текстовый кусок PNG.

## Ширина заказа — `gerber2msla/patterns.py` (П4)

```
Width                              — неизменяемый (patterns.py:65)
  mm: float | None                 — заказ в миллиметрах
  px: int | None                   — заказ в ЦЕЛЫХ пикселях экрана
  label                            — «6 px» либо «0.200 mm» для отчёта
```

Обе формы заканчиваются одним числом пикселей НА ОСЬ — это единственное, что знает рисование. Обе формы
сразу — отказ `use either … or …, not both`: два ответа на один вопрос не сливаются.

## Квадрат — `gerber2msla/patterns.py` (П5а)

```
build_square(screen, side_x_mm, side_y_mm, line) -> Figure   (patterns.py:252)
  сторона по X/Y квантуется своей осью: n_x, n_y; толщина вертикальных полос w_x,
  горизонтальных w_y; сторона <= 2·линии — Refusal
  Figure  — контур (четыре полосы), внутри чёрное; отчёт несёт формулы замера
```

Две стороны — отдельные аргументы, хотя одиночная команда передаёт одну величину дважды: рамка пластины
(П5б) — та же функция с `side_x ≠ side_y`, отдельной фигуры для рамки не будет.

## Размещение — `gerber2msla/masks.py` (П5б)

```
Placement                                — неизменяемый
  figure: Figure                         — что положить
  x_px / y_px: int                       — куда: левый верхний пиксель
  name: str | None                       — None у одиночного рисунка, имя — у фигуры пластины
  at_mm: tuple | None                    — заказ оператора (для строки отчёта)

compose(screen, placements, mirror=, invert=) -> (image, lines)
  проверки: каждая фигура внутри экрана; пересечение — по НАРИСОВАННЫМ пикселям
            (маска владельцев), не по рамкам, поэтому контур рамки тоже участвует
  зеркало и полярность — ПОСЛЕ размещения, один раз на всю картинку
```

Один путь для одной фигуры и для пластины: одиночная команда передаёт список из одного `Placement`,
второго способа размещения нет.

## Пластина — `gerber2msla/patterns.py` (П5б)

```
build_plate(...) -> (placements, report)
  рамка    — build_square(plate_w - 2·margin, plate_h - 2·margin), стороны по осям
  метка    — одна F, верхний левый угол ВНУТРИ рамки, с зазором MARKER_GAP_MM
  bars     — левая половина; grid — правая; между фигурами и рамкой не меньше зазора
  _require_inside — фигура вне полости рамки: Refusal с именем, мм и пикселями
```

## Файл принтера: ЧТЕНИЕ — `gerber2msla/px6s.py` (П1)

```
FileMark        version, table_count, addresses{name: offset}   — адреса блоков из шапки файла
Header          table_length, pixel_size_um, layer_height_mm, exposure_s, wait_before_cure_s,
                bottom_exposure_s, bottom_layers (float), lift_*, retract_*, anti_aliasing,
                resolution_x, resolution_y
Machine         name, layer_image_format, resolution_x/y, pixel_width/height_um
                (в настоящих файлах поля пикселя и разрешения отсутствуют — длина 156)
LayerInfo       data_address, data_length, lift_height_mm, lift_speed_mm_s, exposure_s,
                layer_height_mm, non_zero_pixels        — одна 32-байтная запись LAYERDEF
Px6sFile        path, mark, header, machine, layers, _data
                layer_count; layer_image(index) -> np.uint8 (height, width)
decode_pw0      RLE «код + длина серии» -> массив (height, width), строка за строкой
```

Поля, смещения и порядок байт — в `docs/format_px6s.md`; каждый блок там назван классом и методом UVtools
`86c7c3c`. Описание — единственный вход и для читателя, и для будущего писателя: код UVtools (C#, AGPL)
не переносится и построчно не переводится.

## Файл принтера: ЗАПИСЬ — `gerber2msla/px6s.py` (план П2, П3)

```
шаблон (вход)                      — настоящий однослойный px6s этого принтера, ТОЛЬКО чтение
что утилита МЕНЯЕТ                 — данные слоя 0 (из PNG), ExposureTime и BottomExposureTime
                                     (оба = --exposure-s), число слоёв = 1, BottomLayerCount = 1,
                                     превью = уменьшенная маска
что утилита НЕ трогает             — всё остальное (EXTRA, MACHINE, SOFTWARE, MODEL, служебные
                                     блоки v517), байт в байт: блоки берутся по адресам
```
