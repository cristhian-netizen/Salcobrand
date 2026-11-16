import {Card} from '../sb/ui';
import {labelOf} from '../navigation/Sidebar';
import {MODULE_HELP} from './helpContent.mjs';

export default function HelpTopics({content, go}) {
  return <>
    <Card title="Tus módulos" subtitle="Funciones disponibles para tu perfil." className="help-topics"><div className="help-module-grid">{content.modules.map(view => <article key={view}><h3>{labelOf(view)}</h3><p>{MODULE_HELP[view]}</p><button type="button" className="link" onClick={() => go(view)}>Ir a {labelOf(view)}</button></article>)}</div></Card>
    <Card title="Preguntas frecuentes" className="help-faq">{content.faqs.map(item => <details key={item.title}><summary>{item.title}</summary><p>{item.text}</p></details>)}</Card>
  </>;
}
