import {Card} from '../sb/ui';

export default function HelpWorkflow({content, go}) {
  return <Card title={content.title} className="help-workflow"><ol>{content.steps.map(step => <li key={step.view}><div><h3>{step.title}</h3><p>{step.text}</p></div><button type="button" onClick={() => go(step.view)}>Abrir módulo <span className="home-sr-only">{step.title}</span><span aria-hidden="true">↗</span></button></li>)}</ol></Card>;
}
