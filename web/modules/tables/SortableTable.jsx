'use client';
import {Children, Fragment, cloneElement, isValidElement, useState} from 'react';
import {compareValues} from '../../lib/table-sort.mjs';

function nodes(children) {
  const result = [];
  Children.forEach(children, node => {
    if (isValidElement(node) && node.type === Fragment) result.push(...nodes(node.props.children));
    else if (node != null && node !== false) result.push(node);
  });
  return result;
}
function text(node) {
  if (!isValidElement(node)) return Array.isArray(node) ? node.map(text).join(' ') : String(node ?? '');
  const p = node.props;
  if (p['data-sort-value'] != null) return p['data-sort-value'];
  if (p.pct != null) return p.pct;
  if (p.value != null && ['input', 'select'].includes(node.type)) return p.value;
  if (p.children == null) return p.label ?? p.status ?? '';
  return nodes(p.children).map(text).join(' ').trim();
}

export default function SortableTable({children, sort: controlled, onSort, serverSort = false, ...props}) {
  const [local, setLocal] = useState(null);
  const sort = controlled === undefined ? local : controlled;
  const change = column => {
    const next = {column, direction: sort?.column === column && sort.direction === 'asc' ? 'desc' : 'asc'};
    if (onSort) onSort(next); else setLocal(next);
  };
  return <table {...props}>{nodes(children).map((section, sectionIndex) => {
    if (!isValidElement(section)) return section;
    if (section.type === 'thead') return cloneElement(section, {key: section.key ?? sectionIndex}, nodes(section.props.children).map((row, index) =>
      cloneElement(row, {key: row.key ?? index}, nodes(row.props.children).map((header, column) => {
        const label = String(text(header));
        if (!label || /^(accion(?:es)?|seleccionar|detalle|evidencia)$/i.test(label.normalize('NFD').replace(/[\u0300-\u036f]/g,'')) || header.props['data-sortable'] === false) return cloneElement(header, {key: header.key ?? column});
        const active = sort?.column === column;
        return cloneElement(header, {key: header.key ?? column, 'aria-sort': active ? (sort.direction === 'asc' ? 'ascending' : 'descending') : 'none'},
          <button type="button" className="table-sort" onClick={() => change(column)} aria-label={'Ordenar por ' + label + (active && sort.direction === 'asc' ? ': descendente' : ': ascendente')}>
            <span>{header.props.children}</span><span aria-hidden="true">{active ? (sort.direction === 'asc' ? '↑' : '↓') : '↕'}</span>
          </button>);
      }))));
    if (section.type === 'tbody' && sort && !serverSort) {
      const rows = nodes(section.props.children);
      const sorted = rows.map((row, index) => ({row, index})).sort((a, b) => {
        const left = nodes(a.row.props?.children)[sort.column], right = nodes(b.row.props?.children)[sort.column];
        return compareValues(text(left), text(right), sort.direction) || a.index - b.index;
      });
      return cloneElement(section, {key: section.key ?? sectionIndex}, sorted.map(({row, index}) => cloneElement(row, {key: row.key ?? index})));
    }
    return cloneElement(section, {key: section.key ?? sectionIndex});
  })}</table>;
}
