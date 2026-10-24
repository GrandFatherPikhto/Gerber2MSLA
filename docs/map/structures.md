# Что лежит в чём (экран / фигура / ширина / файл принтера)

Gerber2MSLA, 23.10.2026: `Screen`, `Figure` и `Width` — код П4 плана `png2px6s`; `px6s` — план П2/П3.
Когда появится код `px6s` — заменить пометки на `файл:строка`, как в Gerber2LDI.

---

## Чтение Gerber и сверловки — `gerber2msla/gerber_source.py` (Г0, КОПИЯ)

```
Shape                              — неизменяемый (gerber_source.py:68)
  polygons: tuple[tuple[Point]]     — замкнутые контуры в мм, как их нарисовал файл
  dark: bool                        — полярность ЭТОГО объекта (LPD — True, LPC — False)
  bbox: (x0, y0, x1, y1)            — габарит, по нему строки отсекают фигуру заранее

Layer                              — неизменяемый (:77)
  shapes: tuple[Shape, ...]         — В ПОРЯДКЕ ФАЙЛА: порядок и есть порядок рисования
  bbox / unit / aperture_count      — габарит слоя, что сказал файл, сколько апертур
  has_clear                         — есть ли в слое хоть один LPC

Hole                               — неизменяемый (:187)
  x_mm / y_mm / diameter_mm         — позиция и ГОТОВЫЙ диаметр (gerbonara отдаёт радиус)

load_layer(path) / load_drill(path) — Refusal вместо чужого InputFileError (:161, :214)
quiet_library()                     — stdout и warnings gerbonara глушатся в DEBUG (:97)
```

Полярность — операция ПОСЛЕДОВАТЕЛЬНОСТИ, а не флаг: `%LPC*%` стирает нарисованное ДО него, поэтому
`shapes` не сортируется ни здесь, ни ниже. Повёрнутый `Rectangle` строится из угла: `to_arc_poly()` в
gerbonara 1.6.3 отдаёт ГАБАРИТ повёрнутого прямоугольника (2×1 мм при 45° меряется как 4.5 мм²).

## Строки по геометрии — `gerber2msla/gerber_rows.py` (Г0, КОПИЯ)

```
Segment                            — (x0, x1) в мм, всегда x0 < x1 (gerber_rows.py:54)
normalize(segments)                — единственный хозяин инварианта строки (:57)
ScanRow(y_mm, segments)            — неизменяемая строка; нормализуется в __post_init__ (:103)

union / subtract                   — полярность на одной строке (:128, :133)
row_y / row_count / ROW_CENTRE     — высота строки и их число (:156, :161, :49)
polygon_intervals                  — где контур покрывает линию y, правило половинного ребра (:183)
row_segments(shapes, y_mm)         — строка с полярностью в порядке файла (:190)
iter_rows(shapes, box, step_y_mm)  — строки снизу вверх; шаг задаёт вызывающий (:207)
```

Строка берётся по ЦЕНТРУ прохода (`ROW_CENTRE = 0.5`): при шаге `pixel_y_mm` это и есть выборка
«ближайшим целым» по Y. Переворот Y в картинку — не здесь: `iter_rows` идёт от низа платы вверх, а
строки PNG — сверху вниз, и это единственное место переворота живёт в `board.build_board`.

## Плата → пиксели — `gerber2msla/board.py` (Г1)

```
build_board(screen, copper, drills=(), outline=None) -> Figure   (board.py:137)
  кадр     — _frame: габарит контура, а без него — габарит меди + warning (:55)
  размер   — width_px = _quantised(…), height_px = row_count(…) — тот же счёт, что у iter_rows
  строки   — iter_rows(layer.shapes, box, pixel_y_mm); image_row = height_px − 1 − index
             — ЕДИНСТВЕННЫЙ переворот Y (:137)
  по X     — _pixel_span: пиксели, чьи ЦЕНТРЫ внутри [a, b) (:73)
  дырки    — _pour_holes: круг диаметром из файла, чёрным ПОСЛЕ меди (:103)
  отчёт    — файл, рамка (мм и px, откуда), отверстия, белые px и мм²; warning: — префиксом
```

Figure — та же, что у `bars`/`grid`: размещение, зеркало, полярность и PNG идут ОДНИМ путём
`masks.compose`, второго нет. Модуль не знает ни про экран целиком, ни про файл принтера.

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

## Надпись — `gerber2msla/font5x7.py` и `patterns.build_text` (Т1)

```
GLYPHS: dict[str, tuple[str, ...]]  — 7 строк по 5 точек ("#" горит, "." нет); набор:
                                      0-9, A-Z, a-z, пробел и . , - _ : / ( ) + = %
GLYPH_WIDTH / GLYPH_HEIGHT         — 5 / 7 точек
LETTER_GAP                         — 1 пустая точка между буквами: ширина (6n − 1) точек

build_text(screen, text, stroke_px) -> Figure
  отказы            пустая строка; stroke_px < 1; символ вне GLYPHS — с СИМВОЛОМ и МЕСТОМ
                    в строке (пробел вместо него не ставится)
  точка шрифта      stroke_px x stroke_px ПИКСЕЛЕЙ экрана, не мм: на пикселе 34 x 30 мкм
                    картинка та же, буквы не кланяются
  отчёт             текст, точка в px и um, набор и размер сетки, размер фигуры в px и мм
  дальше            та же `Placement` → `compose`: размещение, зеркало и полярность
                    особого случая для надписи не знают
```

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

## Файл принтера: ЗАПИСЬ — `gerber2msla/px6s_write.py` (П2)

```
Written          data: bytes, report: tuple[str, ...]
encode_pw0       пиксели -> байты RLE; серии равных старших нибблов, склейка соседних
                 серий одного цвета, 0/255 — до 4095 двумя байтами, прочие — до 15
render_preview   маска -> RGB565 little-endian, nearest-neighbour в размеры шаблона
mark_size        сколько байт занимает file mark версии
write_from_template(template, mask, exposure_s, mirror_x=False) -> Written
  меняет: данные слоя, ExposureTime, BottomExposureTime, BottomLayersCount = 1,
          длину и адрес записи LAYERDEF, NonZeroPixelCount, превью (PREVIEW/PREVIEW2),
          адреса в file mark
  копирует байт в байт: HEADER (кроме обоих времён и числа нижних слоёв), EXTRA,
          MACHINE, SOFTWARE, MODEL, цветовую таблицу, подъёмы/скорости, порядок блоков
write_file       шаблон -> Written -> файл; возвращает путь и строки отчёта
```

`LightPWM` в файл не пишется: в v517 такого поля нет, и отчёт говорит это словами.
Флага зеркала в файле тоже нет: `--mirror-x` — решение оператора.

## Серия по времени — `gerber2msla/dose.py` (П5в)

```
times_from_list(text)              "15,20,25" -> времена; повтор времени — отказ
times_from_series(start, stop, n)  n времён от start до stop, ratio = (stop/start)^(1/(n−1));
                                   COUNT ≥ 2, START < STOP, конечные и > 0
times_from_series_args(values)     разбор слов `--series START STOP COUNT`
series_file(prefix, seconds)       out/dose + 25 -> out/dose_25.0s.px6s
check_names(prefix, times)         два времени с одним именем после округления — отказ
write_series(template, mask, prefix, times)
                                   файл на каждое время ТЕМ ЖЕ писателем; имя и содержимое
                                   берут один и тот же слот лесенки
report(files)                      таблица «файл → обычное и нижнее», прочитанная ИЗ файлов
```

## CLI — четыре модуля (Г2, П2, П3, П5в, Б2)

```
cli.py        корень: prog, --version, сборка подкоманд, ловля Refusal/Px6sError, код 2
cli_masks.py  группа `masks`: bars, grid, square, plate (перенесена без изменения флагов)
cli_px6s.py   `write`: маска PNG -> write_file -> отчёт; `dump`: read_file -> строки
              -> stdout, по `-o` слой 0 в PNG; `dose`: времена -> dose.write_series -> таблица
cli_board.py  `board`: одна медь или `--config`; BOARD_FLAGS — что рядом с конфигом отказ
              по имени; экран и пиксель — screen_choice.screen_for; работа — board_files
```

Маски НЕ переезжают в px6s-модуль: разделение — «маски здесь, write/dump/dose там».

## Конфиг пластины — `gerber2msla/plate_config.py` и `plate_layout.py` (К1, К2)

```
PlateConfig                     — прочитанный конфиг, ещё БЕЗ пикселей
  width_mm, height_mm: float    — размер пластины
  exposure_s: tuple | None      — времена серии, в порядке файла; None = ключа нет
  times                         — свойство: (None,) если ключа нет, иначе сам кортеж:
                                  один файл на запись
  marker_at_mm: tuple | None    — None = [marker] нет = метки нет
  figures: tuple[FigureSpec,…]  — в порядке ФАЙЛА
  output: PlateOutput           — [output] (Б0): принтер и выход
  text: str                     — файл целиком, как прочитан (уезжает в кусок PNG)
  rotate: int = 0               — поворот готовой пластины против часовой (0/90/180/270)
  path: Path | None             — для сообщений; None у текста из памяти
  label                         — «<config>» или путь

PlateOutput                     — всё про принтер, ни одного «умолчания»
  template: Path                — ОБЯЗАТЕЛЕН всегда: экран и пиксель заголовка — из него
  pixel_um: tuple | None        — ЗАМЕР: меняет геометрию, заголовок файла — нет (Г2)
  px6s, png: Path | None        — хотя бы один («the config writes nothing»); оба — из
                                  ОДНОЙ картинки compose

FigureSpec = SquareSpec | GridSpec | BarsSpec | PatchesSpec | TextSpec

TextSpec                        — надпись (Т1): text: str, stroke_px: int (целое ≥ 1)
  name: str                     — «kind #N», N с 1 по порядку в файле: этим именем
                                  фигуру называют отказы compose и пластины
  at_mm: tuple                  — левый верхний угол ОТ УГЛА ПЛАСТИНЫ
  … свои ключи вида              — SquareSpec size_mm+line; GridSpec + gap+direction;
                                  BarsSpec widths+lines; PatchesSpec patch_mm+
                                  patch_gap_mm+widths+gap (None = «зазор = ширина»)

parse_plate_config(text, *, source=…, base=None, path=None) -> PlateConfig
  tomllib.loads; TOMLDecodeError -> Refusal с НОМЕРОМ СТРОКИ (lineno, затем текст)
  _table/_keys/_required  — на КАЖДОМ уровне: корень, [output], [plate], [marker], фигура,
                            {from,to,step}; умолчаний нет ни у одного ключа
  _number/_whole/_pair/_string/_flag — bool не число, px только целое, пара ровно из двух
  _widths/_range        — список ИЛИ {from, to, step} включительно, допуск 1e-9
  _resolve/_must_exist  — пути от КАТАЛОГА КОНФИГА (normpath); нет входного файла — отказ
                          с КЛЮЧОМ и путём
load_plate_config(path) — read_text UTF-8 -> parse -> _must_exist(шаблон); нет файла или
                          не UTF-8 — Refusal одной строкой

_times                — [plate] exposure_s: число ИЛИ массив; пустой массив и повтор
                        времени — отказ; None = ключа нет
_rotation             — [plate] rotate: 0/90/180/270, нет ключа — 0; иное — отказ
_placeholders         — в text И в путях одна подстановка {exposure_s}; иная скобка —
                        отказ с НОМЕРОМ СИМВОЛА
_series_output        — у серии КАЖДЫЙ путь [output] обязан держать {exposure_s}, иначе
                        отказ: файлы затёрли бы друг друга
fill_text(text, exposure_s) — подстановка времени без хвоста нулей (20, 7, 2.5); нет
                        exposure_s — отказ с именем ключа
fill_path(path, exposure_s) — то же для ИМЕНИ файла; нет подстановки — путь как есть

build_config_plate(screen, config, seconds=None) -> (placements, report)
  seconds               — время ЭТОГО файла: серия зовёт функцию на каждое время, и надпись
                          `{exposure_s}` говорит своё время, а не первое из списка
  пластина: _quantised по каждой оси; фигуры кладутся на ХОЛСТ РАЗМЕРОМ ПЛАСТИНЫ
  _require_on_plate     — пластина больше экрана и фигура за пластиной — отказ с именем
  _corner_px            — at_mm / pitch по СВОЕЙ оси, round; ноль законен
  _figure_of            — та же build_*, что у одиночной команды; надпись получает
                          fill_text(spec.text, seconds)
  compose(холст, …)     — холст собирается ОДНИМ compose: пересечения — его отказы
  np.rot90(…)           — rotate != 0: ГОТОВАЯ картинка поворачивается ПРОТИВ часовой;
                          четверть оборота на неквадратном пикселе — отказ
  place_figure(…, None) — повёрнутая пластина ставится по центру, и compose кладёт её на
                          экран ОДНОЙ фигурой «plate» (зеркало и полярность — тот же путь)
```

Кусок PNG: `masks.write_mask(..., config_text=…)` кладёт текст конфига в iTXt под ключом
`plate_config`; кусок отчёта `msla_tests` при этом не меняется — на этом стоит оракул К2
(«пример = зашитая раскладка» сравнивается по пикселям).

## Сторож мусора оснасток — `tools/repo_guard.py` (правило 25.10)

```
changed(root=ROOT) -> set[str]        — пути из `git status --porcelain`
leaked(before, root=ROOT) -> set[str] — что ПОЯВИЛОСЬ с `before`: бывшее до прогона — не мусор
```

Грязное дерево на старте — норма (там может лежать работа Дениса): оснастка запоминает
`before` и судит только о новом. LEAK — промах со списком путей; сторож НИЧЕГО не удаляет
(функции удаления у него нет), мусор убирает тот, кто смотрит. Клетки —
`tests/test_repo_guard.py`: чужой неотслеживаемый файл на месте и не изменён.

## Строгие помощники — `gerber2msla/config_strict.py` (Б1, переезд из `plate_config.py`)

```
_keys(table, known, where, source)        — неизвестный ключ: отказ с ИМЕНЕМ и списком известных
_required(table, key, where, source)      — отсутствующий ключ: «no defaults», отказ с именем
_number/_whole/_pair/_flag/_text/_string  — тип: bool НЕ число (сравнение по identity)
_syntax_line(error)                       — TOMLDecodeError.lineno/colno (3.14) или regex (3.11/3.12)
_loads/_read_text                         — tomllib.loads; файл читается UTF-8, иначе отказ
_resolve(value, base)                     — относительный путь от КАТАЛОГА КОНФИГА, normpath
_must_exist(target, key, where, source)   — нет входного файла: отказ с КЛЮЧОМ и путём
```

Один модуль на два конфига: таблицы ключей объявляет каждый конфиг (`FIGURE_KEYS`,
`OUTPUT_KEYS`, `BOARD_KEYS`, `SIDE_KEYS`), отказы — общие. Второй копии разбора нет.

## Конфиг платы — `gerber2msla/board_config.py` (Б1) и `board_files.py` (Б2)

```
BoardConfig                     — прочитанная плата, ещё БЕЗ пикселей
  outline: Path                 — ОБЯЗАТЕЛЕН: одна рамка на все файлы платы
  drills: tuple[Path, …]        — пусто законно (тент), но align_s или holes = true без них — отказ
  output: BoardOutput           — [output]: template, dir, png (bool), необязательный pixel_um
  sides: tuple[SideSpec, …]     — в порядке файла; имена уникальны и файловые
  text: str, path: Path | None, label
  pixel_um                      — свойство: output.pixel_um (замер; заголовок не меняется)

SideSpec
  name: str                     — [a-z0-9_-]+; из него <name>.px6s и <name>_align.px6s
  copper, mirror, holes, exposure_s, align_s: float | None
  exposure_file / align_file    — имена файлов: ОДНО место их сборки

parse_board_config(text, *, source, base, path) -> BoardConfig
load_board_config(path)         — плюс _must_exist на шаблон, контур, сверловку и медь сторон

write_board(screen, config, *, pixel_line) -> tuple[str, …]
  папка        [output] dir, mkdir(parents=True); перезапись разрешена (строка overwrote)
  _picture     build_board(drills по with_holes) -> compose(зеркало стороны): ОДНА картинка
  _write_px6s  П2-писатель, второго пути записи нет; своё время на каждый файл
  _write_png   тот же кадр в PNG, текст конфига целым (write_mask(config_text=…))
  _without_frame  строка frame: печатается ОДИН раз на всю плату (в кусках PNG — в каждом)
  _drilled     строки сверловки фигуры как есть: второго счёта отверстий нет
  board_report.txt  отчёт целиком + текст конфига
```

Экран и пиксель выбирает вызывающий: `cli_board` зовёт `screen_choice.screen_for` с
`SimpleNamespace(screen_px=None, pixel_um=config.pixel_um)` — тот же ответ, что у одиночной
команды (шаблон фиксирует экран, замер меняет только геометрию).

## Команда `dump` — `gerber2msla/cli_px6s.py` (П3)

```
add_parser    `write` и `dump`: позиционный file, -o — PNG слоя 0 (необязателен)
_dump_lines   Px6sFile -> строки: файл, версия и число блоков, станок и формат слоя,
              разрешение и пиксель, оба времени, нижние слои и число слоёв, высота и
              скорости подъёма/отвода, строка на каждый слой (адрес, длина, подъём,
              время, nonzero), адреса блоков по возрастанию
_cmd_dump     read_file -> _dump_lines -> stdout; с -o: layer_image(0) -> PNG `L`
```

Байтовых знаний не добавляет: печатается то, что уже разобрал `px6s.py`.
