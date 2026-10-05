#!/usr/bin/env node
/* Генерує Word-звіт з metrics.json (цифри) і narrative.json (висновки).
 *   node build_docx.js metrics.json narrative.json report.docx
 * Потрібен пакет docx (npm). */
const fs = require('fs');
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell, HeadingLevel, AlignmentType,
  LevelFormat, WidthType, ShadingType, BorderStyle, ExternalHyperlink,
} = require('docx');

const [, , mPath, nPath, outPath] = process.argv;
if (!mPath || !nPath || !outPath) { console.error('Використання: node build_docx.js metrics.json narrative.json out.docx'); process.exit(1); }
const m = JSON.parse(fs.readFileSync(mPath, 'utf8'));
const n = JSON.parse(fs.readFileSync(nPath, 'utf8'));

const FONT = 'Arial', ACCENT = '1F4E79', GREY = 'F2F2F2', W = 9638;
const MONTHS = ['січня','лютого','березня','квітня','травня','червня','липня','серпня','вересня','жовтня','листопада','грудня'];
const dm = (s) => { const d = new Date(s.slice(0, 10) + 'T00:00:00Z'); return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]}`; };
const dmy = (s) => `${dm(s)} ${s.slice(0, 4)}`;
const num = (x) => (x === null || x === undefined ? '—' : String(Math.round(x * 10) / 10).replace('.', ','));
const short = (s, k = 70) => { s = (s || '').split(/\s+/).join(' '); return s.length <= k ? s : s.slice(0, k - 1) + '…'; };
const base = (m.meta.baseUrl || '').replace(/\/$/, '');

const run = (text, o = {}) => new TextRun({ text, font: FONT, size: 22, ...o });
const para = (kids, o = {}) => new Paragraph({ spacing: { after: 120, line: 276 }, children: Array.isArray(kids) ? kids : [run(kids)], ...o });
const paras = (t) => (t || '').split(/\n\n/).filter((x) => x.trim()).map((x) => para(x.trim()));
const h1 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_1, keepNext: true, spacing: { before: 320, after: 140 }, children: [new TextRun({ text: t, font: FONT, bold: true, size: 30, color: ACCENT })] });
const h2 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_2, keepNext: true, spacing: { before: 200, after: 100 }, children: [new TextRun({ text: t, font: FONT, bold: true, size: 24, color: '333333' })] });
const bullet = (parts) => new Paragraph({ numbering: { reference: 'bul', level: 0 }, spacing: { after: 80, line: 276 },
  children: parts.map((x) => (typeof x === 'string' ? run(x) : x)) });
const note = (t) => para([run(t, { italics: true, color: '595959', size: 20 })], { spacing: { before: 100, after: 120 } });

const border = { style: BorderStyle.SINGLE, size: 4, color: 'BFBFBF' };
const borders = { top: border, bottom: border, left: border, right: border };
function cell(content, width, o = {}) {
  const kids = typeof content === 'string' || typeof content === 'number'
    ? [new TextRun({ text: String(content), font: FONT, size: 19, bold: !!o.bold, color: o.color })] : content;
  return new TableCell({
    width: { size: width, type: WidthType.DXA }, borders,
    margins: { top: 60, bottom: 60, left: 100, right: 100 },
    shading: o.fill ? { fill: o.fill, type: ShadingType.CLEAR, color: 'auto' } : undefined,
    children: [new Paragraph({ keepNext: true, alignment: o.align || AlignmentType.LEFT, children: kids })],
  });
}
// widths: масив DXA, сума = W; firstLeft: перша колонка вирівняна вліво, решта по центру; leftCols: індекси колонок вліво
function table(widths, head, rows, leftCols = [0]) {
  const total = widths.reduce((a, c) => a + c, 0);
  const al = (i) => (leftCols.includes(i) ? AlignmentType.LEFT : AlignmentType.CENTER);
  return new Table({
    width: { size: total, type: WidthType.DXA }, columnWidths: widths,
    rows: [
      new TableRow({ tableHeader: true, cantSplit: true, children: head.map((t, i) => cell(t, widths[i], { fill: ACCENT, bold: true, color: 'FFFFFF', align: al(i) })) }),
      ...rows.map((r, ri) => new TableRow({ cantSplit: true, children: r.map((t, i) => cell(t, widths[i], { fill: ri % 2 ? GREY : undefined, align: al(i) })) })),
    ],
  });
}
const idCell = (id) => base
  ? [new ExternalHyperlink({ link: `${base}/work_packages/${id}`, children: [new TextRun({ text: String(id), font: FONT, size: 19, style: 'Hyperlink', color: '0563C1', underline: {} })] })]
  : String(id);
const spacer = () => new Paragraph({ spacing: { after: 60 }, children: [] });

const { meta, overview: ov, flow: fl, aging: ag, deadlines: dl, hygiene: hy } = m;
const kids = [];
kids.push(new Paragraph({ spacing: { after: 60 }, children: [new TextRun({ text: n.title || 'Звіт по задачах команди', font: FONT, bold: true, size: 44, color: ACCENT })] }));
kids.push(new Paragraph({ spacing: { after: 240 }, border: { bottom: { style: BorderStyle.SINGLE, size: 8, color: ACCENT, space: 6 } },
  children: [run(`${n.subtitle ? n.subtitle + ' · ' : ''}тиждень ${dm(meta.weekStart)} – ${dmy(meta.weekEnd)}`, { color: '595959', size: 20 })] }));

kids.push(h1('1. Головне за тиждень'));
(n.summary || []).forEach((s) => kids.push(bullet([run(s.lead + ' ', { bold: true }), s.text])));

kids.push(h1('2. Ключові цифри'));
kids.push(table([3638, 2000, 2000, 2000], ['Показник', 'Тиждень', 'Попередній', 'Середнє за 4 тижні'], [
  ['Закрито задач', ov.doneWeek, ov.donePrev, num(ov.doneAvg4)],
  ['Створено нових задач', ov.createdWeek, ov.createdPrev, '—'],
  ['Зараз у роботі', ov.wip, '—', '—'],
  ['Зараз чекає тестування', ov.review, '—', '—'],
  ['Зараз у беклозі', ov.backlog, '—', '—'],
]));
kids.push(h2('Швидкість виконання, останні 28 днів'));
const c = fl.current28d, p = fl.previous28d;
const pc = (o) => `${o.n} (${Math.round((o.share || 0) * 100)}%)`;
kids.push(table([4638, 2500, 2500], ['Показник', 'Останні 28 днів', 'Попередні 28 днів'], [
  ['Cycle time, медіана (діб)', num(c.cycle.median), num(p.cycle.median)],
  ['Cycle time, 85-й перцентиль (діб)', num(c.cycle.p85), num(p.cycle.p85)],
  ['Lead time, медіана (діб)', num(c.lead.median), num(p.lead.median)],
  ['Lead time, 85-й перцентиль (діб)', num(c.lead.p85), num(p.lead.p85)],
  ['Закрито у день створення', pc(c.closedWithinDayOfCreation), pc(p.closedWithinDayOfCreation)],
  ['Задач у вибірці (cycle / lead)', `${c.cycle.n} / ${c.lead.n}`, `${p.cycle.n} / ${p.lead.n}`],
]));
kids.push(note('Cycle time рахується від першого переходу в «In progress» до «Done», lead time від створення до «Done».'));

kids.push(h1('3. Рух роботи'));
kids.push(...paras(n.flow));
kids.push(table([3638, 3000, 3000], ['Тиждень з', 'Закрито', 'Створено'], m.trend.map((t) => [dm(t.weekStart), t.done, t.created])));

kids.push(h1('4. Навантаження та години по людях'));
kids.push(...paras(n.people));
const rel = m.people.filter((x) => x.relevant);
kids.push(table([2238, 1100, 1100, 1100, 1000, 1000, 1000, 1100],
  ['Людина', 'Годин за тиждень', 'Попер. тиждень', 'Середнє за 4 тижні', 'У роботі', 'У тесті', 'Беклог', 'Закрито'],
  rel.map((x) => [x.name, num(x.hoursWeek), num(x.hoursPrev), num(x.hoursAvg4), x.inProgress, x.inReview, x.backlog, x.doneWeek])));
const flagged = rel.filter((x) => x.flags.length);
if (flagged.length) {
  kids.push(h2('Що привертає увагу'));
  flagged.forEach((x) => kids.push(bullet([run(x.name + ': ', { bold: true }), x.flags.join('; ') + '.'])));
}
if (m.people.length - rel.length > 0) kids.push(note(`Ще ${m.people.length - rel.length} осіб мають задачі в беклозі, але без активності за період, у таблиці не показані.`));

kids.push(h1('5. Аномалії та ризики'));
(n.anomalies || []).forEach((a) => { kids.push(h2(a.title)); kids.push(...paras(a.text)); });

kids.push(h1('6. Задачі, що потребують уваги'));
if (dl.overdue.length) {
  kids.push(h2(`Прострочені (${dl.overdueCount}, найстаріші)`));
  kids.push(table([800, 4038, 1900, 1500, 1400], ['№', 'Задача', 'Виконавець', 'Статус', 'Прострочено, діб'],
    dl.overdue.map((x) => [idCell(x.id), short(x.subject), x.assignee || '—', x.status, x.overdueDays]), [1, 2, 3]));
}
if (dl.dueSoon.length) {
  kids.push(h2(`Дедлайн у найближчі 7 днів (${dl.dueSoonCount})`));
  kids.push(table([800, 4038, 1900, 1500, 1400], ['№', 'Задача', 'Виконавець', 'Статус', 'Дедлайн'],
    dl.dueSoon.map((x) => [idCell(x.id), short(x.subject), x.assignee || '—', x.status, dm(x.dueDate)]), [1, 2, 3]));
}
if (ag.wipOver.length) {
  kids.push(h2(`Давно «в роботі» (понад ${meta.config.aging_days} днів: ${ag.wipOverCount})`));
  kids.push(table([800, 5238, 2200, 1400], ['№', 'Задача', 'Виконавець', 'Днів у статусі'],
    ag.wipOver.map((x) => [idCell(x.id), short(x.subject), x.assignee || '—', x.days]), [1, 2]));
}
kids.push(h2('Скільки задач чекає тестування'));
const bk = ag.reviewBuckets;
kids.push(table([5638, 4000], ['Вік у черзі', 'Задач'], [['до 7 днів', bk['0-7']], ['8–14 днів', bk['8-14']], ['15–30 днів', bk['15-30']], ['понад 30 днів', bk['31+']]]));

kids.push(h1('7. Що рекомендую зробити'));
(n.recommendations || []).forEach((r) => kids.push(bullet([run(r.when + ': ', { bold: true }), r.text])));

kids.push(h1('8. Примітки до даних'));
const autoNotes = [
  meta.excludedWorkPackages ? `Із розрахунків виключено ${meta.excludedWorkPackages} демонстраційних і тестових задач.` : null,
  `Цифри за годинами враховують лише записи, які люди внесли в OpenProject до моменту збору даних (${meta.dataGeneratedAt.slice(0, 16).replace('T', ' ')} UTC).`,
  `Дати завершення проставлені не в усіх задачах: без дедлайну ${hy.openNoDueDate} із ${ov.openLeaf} відкритих.`,
].filter(Boolean);
[...autoNotes, ...(n.notes || [])].forEach((t) => kids.push(bullet([t])));

const doc = new Document({
  creator: 'Claude', title: n.title || 'Звіт по задачах команди',
  styles: { default: { document: { run: { font: FONT, size: 22 } } } },
  numbering: { config: [{ reference: 'bul', levels: [{ level: 0, format: LevelFormat.BULLET, text: '•', alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 540, hanging: 270 } } } }] }] },
  sections: [{ properties: { page: { size: { width: 11906, height: 16838 }, margin: { top: 1134, bottom: 1134, left: 1134, right: 1134 } } }, children: kids }],
});
Packer.toBuffer(doc).then((b) => { fs.writeFileSync(outPath, b); console.log('Готово:', outPath); });
