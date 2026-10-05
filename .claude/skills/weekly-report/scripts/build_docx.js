#!/usr/bin/env node
/* Генерує Word-звіт з metrics.json (цифри) і narrative.json (висновки).
 *   node build_docx.js metrics.json narrative.json report.docx
 * Потрібен пакет docx (npm). */
const fs = require('fs');
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell, HeadingLevel, AlignmentType,
  LevelFormat, WidthType, ShadingType, BorderStyle, ExternalHyperlink,
} = require('docx');

const [, , wdPath, nPath, outPath] = process.argv;
if (!wdPath || !nPath || !outPath) { console.error('Використання: node build_docx.js <workdir> narrative.json out.docx'); process.exit(1); }
const path = require('path');
const plist = JSON.parse(fs.readFileSync(path.join(wdPath, 'projects.json'), 'utf8'));
const n = JSON.parse(fs.readFileSync(nPath, 'utf8'));
const pn = n.projects || {};
const ms = {};
plist.forEach((p) => { ms[p.name] = JSON.parse(fs.readFileSync(path.join(wdPath, 'metrics', p.file), 'utf8')); });
const first = ms[plist[0].name];
let m = first; // перевизначається для кожного проєкту

const FONT = 'Arial', ACCENT = '1F4E79', GREY = 'F2F2F2', W = 9638;
const MONTHS = ['січня','лютого','березня','квітня','травня','червня','липня','серпня','вересня','жовтня','листопада','грудня'];
const dm = (s) => { const d = new Date(s.slice(0, 10) + 'T00:00:00Z'); return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]}`; };
const dmy = (s) => `${dm(s)} ${s.slice(0, 4)}`;
const num = (x) => (x === null || x === undefined ? '—' : String(Math.round(x * 10) / 10).replace('.', ','));
const short = (s, k = 70) => { s = (s || '').split(/\s+/).join(' '); return s.length <= k ? s : s.slice(0, k - 1) + '…'; };
const base = (first.meta.baseUrl || '').replace(/\/$/, '');

const run = (text, o = {}) => new TextRun({ text, font: FONT, size: 22, ...o });
const para = (kids, o = {}) => new Paragraph({ spacing: { after: 120, line: 276 }, children: Array.isArray(kids) ? kids : [run(kids)], ...o });
const paras = (t) => (t || '').split(/\n\n/).filter((x) => x.trim()).map((x) => para(x.trim()));
const h1 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_1, keepNext: true, spacing: { before: 320, after: 140 }, children: [new TextRun({ text: t, font: FONT, bold: true, size: 30, color: ACCENT })] });
const h3 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_3, keepNext: true, spacing: { before: 140, after: 80 }, children: [new TextRun({ text: t, font: FONT, bold: true, size: 22, color: '444444' })] });
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

function projectKids(m, n) {
  const { meta, overview: ov, flow: fl, aging: ag, deadlines: dl } = m;
  const kids = [];
  if (n.headline) kids.push(para([run(n.headline, { bold: true })]));
  if ((n.summary || []).length) {
    kids.push(h2('Головне за тиждень'));
    n.summary.forEach((s) => kids.push(bullet([run(s.lead + ' ', { bold: true }), s.text])));
  }
  const rows = [
    ['Закрито задач', ov.doneWeek, ov.donePrev, num(ov.doneAvg4)],
    ['Створено нових задач', ov.createdWeek, ov.createdPrev, '—'],
    ['Відкритих зараз', ov.openLeaf, '—', '—'],
  ];
  if (ov.wip || ov.review) rows.push(['Із них у роботі / чекає тестування', `${ov.wip} / ${ov.review}`, '—', '—']);
  kids.push(h2('Ключові цифри'));
  kids.push(table([3638, 2000, 2000, 2000], ['Показник', 'Тиждень', 'Попередній', 'Середнє за 4 тижні'], rows));
  const c = fl.current28d, p = fl.previous28d;
  if (c.cycle.n || p.cycle.n) {
    kids.push(note(`Cycle time (від початку роботи до закриття), медіана: ${num(c.cycle.median)} діб за останні 28 днів проти ${num(p.cycle.median)} за попередні; 85-й перцентиль ${num(c.cycle.p85)} проти ${num(p.cycle.p85)} (вибірка ${c.cycle.n} / ${p.cycle.n} задач).`));
  }
  if (n.flow) {
    kids.push(h2('Рух роботи'));
    kids.push(...paras(n.flow));
    if (m.trend.some((t) => t.done || t.created)) kids.push(table([3638, 3000, 3000], ['Тиждень з', 'Закрито', 'Створено'], m.trend.map((t) => [dm(t.weekStart), t.done, t.created])));
  }
  const rel = m.people.filter((x) => x.relevant);
  if (rel.length || n.people) {
    kids.push(h2('Люди та години'));
    kids.push(...paras(n.people));
  }
  if (rel.length) {
    kids.push(table([2238, 1100, 1100, 1100, 1000, 1000, 1000, 1100],
      ['Людина', 'Годин за тиждень', 'Попер. тиждень', 'Середнє за 4 тижні', 'У роботі', 'У тесті', 'Беклог', 'Закрито'],
      rel.map((x) => [x.name, num(x.hoursWeek), num(x.hoursPrev), num(x.hoursAvg4), x.inProgress, x.inReview, x.backlog, x.doneWeek])));
    kids.push(note('Години тут лише за задачами цього проєкту.'));
  }
  if ((n.anomalies || []).length) {
    kids.push(h2('Аномалії та ризики'));
    n.anomalies.forEach((a) => { kids.push(h3(a.title)); kids.push(...paras(a.text)); });
  }
  const att = [];
  if (dl.overdue.length) {
    att.push(h3(`Прострочені (${dl.overdueCount}, найстаріші)`));
    att.push(table([800, 4038, 1900, 1500, 1400], ['№', 'Задача', 'Виконавець', 'Статус', 'Прострочено, діб'],
      dl.overdue.map((x) => [idCell(x.id), short(x.subject), x.assignee || '—', x.status, x.overdueDays]), [1, 2, 3]));
  }
  if (dl.dueSoon.length) {
    att.push(h3(`Дедлайн у найближчі 7 днів (${dl.dueSoonCount})`));
    att.push(table([800, 4038, 1900, 1500, 1400], ['№', 'Задача', 'Виконавець', 'Статус', 'Дедлайн'],
      dl.dueSoon.map((x) => [idCell(x.id), short(x.subject), x.assignee || '—', x.status, dm(x.dueDate)]), [1, 2, 3]));
  }
  if (ag.wipOver.length) {
    att.push(h3(`Давно «в роботі» (понад ${meta.config.aging_days} днів: ${ag.wipOverCount})`));
    att.push(table([800, 5238, 2200, 1400], ['№', 'Задача', 'Виконавець', 'Днів у статусі'],
      ag.wipOver.map((x) => [idCell(x.id), short(x.subject), x.assignee || '—', x.days]), [1, 2]));
  }
  const bk = ag.reviewBuckets;
  if (Object.values(bk).reduce((a, v) => a + v, 0) >= 5) {
    att.push(h3('Скільки задач чекає тестування'));
    att.push(table([5638, 4000], ['Вік у черзі', 'Задач'], [['до 7 днів', bk['0-7']], ['8–14 днів', bk['8-14']], ['15–30 днів', bk['15-30']], ['понад 30 днів', bk['31+']]]));
  }
  if (att.length) { kids.push(h2('Задачі, що потребують уваги')); kids.push(...att); }
  if ((n.recommendations || []).length) {
    kids.push(h2('Що рекомендую зробити'));
    n.recommendations.forEach((r) => kids.push(bullet([run(r.when + ': ', { bold: true }), r.text])));
  }
  if ((n.notes || []).length) {
    kids.push(h2('Примітки'));
    n.notes.forEach((t) => kids.push(bullet([t])));
  }
  return kids;
}

const meta0 = first.meta;
const kids = [];
kids.push(new Paragraph({ spacing: { after: 60 }, children: [new TextRun({ text: n.title || 'Звіт по задачах по проєктах', font: FONT, bold: true, size: 44, color: ACCENT })] }));
kids.push(new Paragraph({ spacing: { after: 240 }, border: { bottom: { style: BorderStyle.SINGLE, size: 8, color: ACCENT, space: 6 } },
  children: [run(`${n.subtitle ? n.subtitle + ' · ' : ''}тиждень ${dm(meta0.weekStart)} – ${dmy(meta0.weekEnd)}`, { color: '595959', size: 20 })] }));
const shown = plist.filter((p) => pn[p.name]);
kids.push(h1('Проєкти'));
kids.push(table([3238, 1500, 1700, 1700, 1500], ['Проєкт', 'Відкрито', 'Закрито за тиждень', 'Створено за тиждень', 'Годин за тиждень'],
  shown.map((p) => [p.name, p.open, p.doneWeek, p.createdWeek, num(p.hoursWeek)])));
shown.forEach((p, i) => {
  kids.push(new Paragraph({ pageBreakBefore: i === 0 || !!pn[p.name].flow, heading: HeadingLevel.HEADING_1, keepNext: true, spacing: { before: 0, after: 140 },
    children: [new TextRun({ text: `${i + 1}. ${p.name}`, font: FONT, bold: true, size: 32, color: ACCENT })] }));
  kids.push(...projectKids(ms[p.name], pn[p.name]));
});
kids.push(note(`Дані OpenProject станом на ${meta0.dataGeneratedAt.slice(0, 16).replace('T', ' ')} UTC. Години враховують лише записи, які люди внесли до цього моменту. Із розрахунків виключено задачі, створені до дати відсічення в config.json (демо й тестові дані).`));

const doc = new Document({
  creator: 'Claude', title: n.title || 'Звіт по задачах команди',
  styles: { default: { document: { run: { font: FONT, size: 22 } } } },
  numbering: { config: [{ reference: 'bul', levels: [{ level: 0, format: LevelFormat.BULLET, text: '•', alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 540, hanging: 270 } } } }] }] },
  sections: [{ properties: { page: { size: { width: 11906, height: 16838 }, margin: { top: 1134, bottom: 1134, left: 1134, right: 1134 } } }, children: kids }],
});
Packer.toBuffer(doc).then((b) => { fs.writeFileSync(outPath, b); console.log('Готово:', outPath); });
