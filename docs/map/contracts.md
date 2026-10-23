# Сквозные договоры — читать ДО задания и ДО приёмки

Gerber2MSLA, 23.10.2026, по образцу Gerber2LDI `docs/map/contracts.md`. Договоры действуют в КАЖДОЙ
задаче, независимо от того, назвало их задание или нет. Одна строка сути + где держится в коде + сторож +
канон. Расходится с кодом — прав код, сводку поправить. «—» в колонке сторожа — сторожа нет, держится на
приёмке.

Каноны: дизайн — `techdocs/handoff/claude/design/design_2026_10_23_gerber2msla.md` (дальше «Д §N»); план —
`techdocs/handoff/deepseek/plan_2026_10_23_png2px6s.md` (дальше «план П…»); правила —
`techdocs/rules/deepseek.md` (дальше «п.N»).

## Маска и экран

| договор | суть | где в коде | сторож | канон |
|---|---|---|---|---|
| **Ширина — ЦЕЛОЕ число пикселей своей оси** | `n = round(ширина / шаг)` по КАЖДОЙ оси; округление, не усечение (иначе каждая линия систематически тоньше заказанной); `n = 0` — отказ с числом и осью | `gerber2msla/masks.py` (`_quantised`) | `test_masks.py`: `test_a_width_below_one_pixel_is_refused`, `test_the_png_remembers_what_it_is` (отчёт печатает 7 px = 210.0 um на неквадратном пикселе — усечение дало бы 6); `test_patterns.py`: `test_a_width_is_whole_pixels_of_its_own_axis` | план П0, П4; отчёт Gerber2LDI §4.1 |
| **Отклонение > 10 % объявляется** | только у мм-заказа: `|нарисованное / заказанное − 1| > 0.10` — строка `warning:` в stderr и в PNG; пиксельный заказ не отклоняется по определению | `gerber2msla/patterns.py` (`_deviation`) | `test_patterns.py`: `test_a_millimetre_request_announces_a_deviation_over_ten_percent` (мутация «предупреждение отключено» убита этой клеткой) | план П4 |
| **Форма заказа — мм ИЛИ пиксели** | `--widths-mm`/`--widths-px`, `--line-mm`/`--line-px`, `--gap-mm`/`--gap-px`; обе формы сразу — отказ «not both»; пиксельный заказ — ровно `n` пикселей каждой оси | `gerber2msla/patterns.py` (`Width`, `_width_pixels`), `gerber2msla/cli_masks.py` (`_widths`, `_one_width`) | `test_cli_masks.py`: `test_both_forms_at_once_are_refused`, `test_grid_takes_its_line_and_gap_in_whole_pixels`; `test_patterns.py`: `test_a_pixel_request_is_one_count_and_two_physical_widths` | план П4 |
| **Две ширины в одно `n` — предупреждение** | их группы на пластине будут одинаковыми; разные `n` — тишина | `gerber2msla/patterns.py` (`_duplicates`) | `test_patterns.py`: `test_widths_that_share_a_pixel_count_are_announced`, `test_widths_with_different_pixel_counts_say_nothing` | план П4 |
| **Белое = засветить; по умолчанию линии** | негативный резист: светим линии; `--invert` меняет полярность ВСЕЙ картинки | `gerber2msla/masks.py` (`compose`) | `test_masks.py`: `test_mirror_and_invert_are_whole_picture_swaps` | план П0 |
| **Метка F в углу рисунка, рисунок рядом** | F в верхнем левом углу, рисунок сдвигается вправо через промежуток; поверх рисунка не рисуется — иначе испортит то, что меряет; F несимметрична по X и Y | `gerber2msla/masks.py` (`marker_pixels`, `add_marker`) | `test_masks.py`: клетки метки | план П4 |
| **Зеркало — только по флагу** | утилита сама не отражает; `display_mirror_x = 1` у экрана — что делает файл, выясняется по описанию формата, проверка — меткой F на пластине | `gerber2msla/masks.py` (`compose`), `gerber2msla/cli.py` (`--mirror`) | `test_masks.py`: `test_the_marker_moves_with_the_mirror` | Д §2; план П2 |
| **Строка зеркала несёт ЧИСЛА** | отчёт называет ЛЕВЫЙ край фигуры после отражения: `W − x − w` (не `W − 1 − x` — это её правый пиксель); у одиночной маски строка байт в байт как в Gerber2LDI `364fd28`, у пластины — строка на каждую фигуру, в px и мм | `gerber2msla/masks.py` (`_flipped_left`, `compose`) | `test_masks.py`: `test_the_mirror_report_says_where_the_figure_lands`; `test_patterns.py`: `test_the_plate_mirror_report_says_where_each_figure_lands`; регрессия `diagnostics/accept_p4_cmp_2026_10_23.py` (png=same, stdout равен кроме `Wrote`) | приёмка П5б 23.10 |
| **PNG маски — ровно экран, `L`, 0/255** | режим `L`, ровно `W×H` пикселей экрана, значения только 0 и 255; иное — отказ | `gerber2msla/masks.py` (`write_mask`) | `test_masks.py`: `test_the_mask_is_the_screen_in_two_values` | план П0 |
| **Экран и пиксель — обязательные аргументы** | `--screen-px` и `--pixel-um` без умолчаний: выдуманное число хуже отказа; пиксель может быть неквадратным | `gerber2msla/cli_masks.py` | `test_cli_masks.py`: `test_the_screen_and_the_pixel_are_mandatory` | план П4 |

## Формат `px6s` (план П1–П3)

| договор | суть | где в коде | сторож | канон |
|---|---|---|---|---|
| **Квадрат: сторона и линия — целые пиксели своей оси** | `side_x`/`side_y` — отдельные аргументы `build_square`; одиночная команда передаёт одну величину дважды, рамка пластины (П5б) — разные; сторона ≤ 2·линии — отказ с числами; отчёт печатает `pixel_um = measured_mm / n · 1000` с числами этого заказа и говорит «outer edge to outer edge» — n есть НАРУЖНЫЙ размер; диагонали — только проверка (`d1 = d2`), формулы перекоса нет | `gerber2msla/patterns.py` (`build_square`), `gerber2msla/cli_masks.py` (`_cmd_square`) | `test_patterns.py`: клетки квадрата (контур, отказ, формулы, наружные края); `test_cli_masks.py`: `test_side_px_reaches_the_square_builder` | план П5а |
| **Пластина: одна метка и фиксированная раскладка** | рамка = квадрат П5а со сторонами `plate - 2·margin`; внутри: ОДНА метка F в верхнем левом углу, `bars` — левая половина, `grid` — правая; промежутки ≥ `MARKER_GAP_MM`; пересечение или фигура за рамкой — ОТКАЗ с именами, мм и пикселями; молча урезать нельзя — умолчания пластины (grid 30x30) названы в отчёте числами | `gerber2msla/patterns.py` (`build_plate`, `_require_inside`), `gerber2msla/cli_masks.py` (`_cmd_plate`) | `test_patterns.py`: `test_every_plate_figure_sits_where_the_report_says`, `test_the_plate_names_the_grid_default_it_uses`, `test_the_mirror_reflects_the_whole_plate_once`, отказы пластины; `test_cli_masks.py`: `test_plate_mm_reaches_the_layout` | план П5б |
| **Зеркало и полярность — один раз на картинку** | `compose` отражает и инвертирует ГОТОВОЕ изображение после размещения всех фигур, а не каждую фигуру по отдельности | `gerber2msla/masks.py` (`compose`) | `test_masks.py`: `test_mirror_and_invert_are_whole_picture_swaps`; `test_patterns.py`: `test_the_mirror_reflects_the_whole_plate_once` | план П5б |
| **Машинное — из шаблона байт в байт** | подъёмы Z, скорости, служебные блоки v517 берутся из настоящего файла принтера и не меняются; пишем только описанные поля: данные слоя, время обычное и нижнее, число слоёв, превью, адреса | `gerber2msla/px6s_write.py` (`write_from_template`), `gerber2msla/px6s.py` (чтение) | `tests/test_px6s_write.py`: `test_the_machine_blocks_stay_byte_for_byte`, `test_writing_the_template_layer_back_gives_the_template_outside_the_preview` | Д §4; п.20; план П2 |
| **Слой 0 в однослойном файле — НИЖНИЙ** | принтер светит его временем нижних слоёв: оба времени = `--exposure-s`, число нижних слоёв = 1; в отчёт — что записано | `gerber2msla/px6s_write.py` (`_patched_blocks`) | `tests/test_px6s_write.py`: круг и отчёт (оба времени 25) | план П2 |
| **PNG для записи — ровно разрешение шаблона** | режим `L`, только 0/255; иное — отказ с размерами и найденными значениями; серое — отдельное решение, флага нет | `gerber2msla/cli_px6s.py` (`_read_mask`), `gerber2msla/px6s_write.py` (`write_from_template`) | `tests/test_px6s_write.py`: отказы; `tests/test_cli_px6s.py`: `test_write_refuses_a_mask_that_is_not_mode_l` | план П2 |
| **Адреса блоков — пересчитаны, длина — до следующего адреса** | после смены длины слоя адреса в file mark и `DataAddress` записи двигаются; поля длины `EXTRA`/`MODEL` не используются | `gerber2msla/px6s_write.py` (`_template_blocks`, `write_from_template`) | `tests/test_px6s_write.py`: `test_a_block_after_the_layer_data_moves_with_it` | план П2 |
| **Формат — из описания, не из чужого кода** | UVtools (C#, AGPL) читается как описание: у каждого поля в `docs/format_px6s.md` — класс и метод UVtools `86c7c3c`; код не переносится и построчно не переводится | `docs/format_px6s.md`, `gerber2msla/px6s.py` | `tests/test_px6s.py`: синтетические файлы по описанию; настоящий шаблон — `tests/data/01_test02.px6s` | п.21; план П1 |
| **`dump` печатает то, что прочитано** | версия, станок, разрешение, пиксель, оба времени, нижние слои и число слоёв, подъёмы и скорости, адреса блоков; `-o` — слой 0 в PNG; числа шаблона сверены с UVtoolsCmd; `-o` пишется только после успешного чтения | `gerber2msla/cli_px6s.py` (`_dump_lines`, `_cmd_dump`) | `tests/test_cli_px6s.py`: `test_dump_prints_the_numbers_uvtools_confirmed`, `test_dump_writes_the_layer_as_a_png`, `test_the_written_plate_dumps_back_as_the_same_png` | план П3 |
| **Адрес блока — истина, длина — нет** | блоки берутся по адресам из file mark; поля длины у `EXTRA`/`MODEL` в настоящих файлах неверны | `gerber2msla/px6s.py` (`_read_mark`, `read_file`) | `tests/test_px6s.py`: `test_the_reader_takes_the_blocks_by_their_addresses` | план П1а |
| **Порядок байт — little-endian** | все поля файла little-endian; big-endian чтение обязано ломаться | `gerber2msla/px6s.py` (`_u32`) | `tests/test_px6s.py`: синтетический файл (мутация «big-endian» убита) | план П1 |

## Слои, файлы, документация

| договор | суть | где в коде | сторож | канон |
|---|---|---|---|---|
| **Без лазерной цепочки** | пакет не импортирует `gerber2ldi`; общее (чтение Gerber, нарезка на строки) берётся зависимостью, когда появится Gerber, а не копией | `gerber2msla/__init__.py` | — | Д §0 |
| **CLI — тонкий** | `cli.py` разбирает аргументы и зовёт ядро; геометрии, единиц и форматов файлов там нет | `gerber2msla/cli.py` | — | план П4 |
| **Пересечение фигур — отказ, не урезание** | две фигуры, нарисовавшие один пиксель, — `Refusal` с именами, мм и px; фигура за экраном — тоже отказ; пластина не сжимает фигуру, чтобы та влезла | `gerber2msla/masks.py` (`compose`), `gerber2msla/patterns.py` (`_require_inside`) | `test_masks.py`: `test_two_figures_that_overlap_are_refused`, `test_a_named_figure_off_the_screen_is_refused_with_its_name` | план П5б |
| **Отказ — одна строка и код 2** | ожидаемые ошибки (`Refusal` масок и `Px6sError` чтения) ловятся в `main`, печатаются одной строкой в stderr, без трассировки; файл результата не появляется | `gerber2msla/cli.py` (`main`), `gerber2msla/masks.py` (`Refusal`), `gerber2msla/px6s.py` (`Px6sError`) | `tests/test_cli.py`: `test_a_refusal_is_one_line_and_code_two` — по строке таблицы на каждый вид отказа | план П4; фикс П2 |
| **Сообщения — ASCII English, без i18n** | пока утилита маленькая: `um`, не `µm`; текст отчёта уезжает в PNG-чанк, поэтому ASCII и там. Это отступление от Gerber2LDI (там gettext) — записано в заметке П0 | `cli.py`, `masks.py`, `patterns.py` | — | п.9; решение 23.10 |
| **Файл ≤ 800 строк, документ ≤ 1200** | новое в разросшийся файл не дописывается — новый модуль; документ подходит к пределу — делить по темам | — | `index.md` (`⚠ >800`), `wc -l` | п.33, п.34 |
| **Карта — в том же заходе** | `index.md` перегенерируется после задания, добавившего/переименовавшего/удалившего модуль или публичную функцию; поменялось правило — правится `map.md` | `tools/project_map.py` | — | п.32 |

## Тесты

| договор | суть | где | сторож | канон |
|---|---|---|---|---|
| **Тестовые входы — синтетика** | маски строятся в `tmp_path`; настоящие файлы принтера — только на чтение в `techdocs/px6s_examples/`; `tests/data/` — только с разрешения Дениса | `tests/` | — | п.16; план П1а |
| **Клетка — на свойство, таблицей** | `@pytest.mark.parametrize`; докстринг называет план и пункт; имя функции описывает свойство и живёт без номера | `tests/test_*.py` | — | п.26, п.28 |
| **Параллельно, две ноги** | `-n auto` только в командах, не в `addopts`; перед сдачей `-n auto` и `-n auto --reverse` | `pytest.ini` | `required_plugins` | п.15 |
| **Сторож не ослабляется** | существующий тест не правится ради зелени: ассерт, входные данные, `skip`/`xfail` — не трогать; красный сторож — чинить код или спрашивать | `tests/` | — | п.24 |

## Границы

| договор | суть | где | сторож | канон |
|---|---|---|---|---|
| **На принтер ничего не отправляется** | пишем только файлы в `out/`; живые засветки — Денис | — | — | п.19 |
| **Коммиты — не наше дело** | репозиторий заводит и коммитит Денис; текст коммита и список файлов — в заметку | `techdocs/handoff/deepseek/` | — | п.7, п.25 |
