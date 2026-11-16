'use client';
import {Header, Card, Pill} from '../sb/ui';
import {ROLE_NAMES} from '../../lib/profiles.mjs';
import {helpFor} from './helpContent.mjs';
import HelpWorkflow from './HelpWorkflow';
import HelpTopics from './HelpTopics';
import SupportChecklist from './SupportChecklist';

export default function Help({user, go}) {
  const content = helpFor(user);
  if (!content) return null;
  return <section className="help-page">
    <Header eyebrow="Guía del portal" title="Ayuda y soporte" subtitle={`Guía para ${user.tenant?.name || 'tu organización'}, según los permisos de tu cuenta.`}><Pill>{ROLE_NAMES[content.role]}</Pill></Header>
    <Card title="Tu perfil y alcance" className="help-profile"><p>{content.overview}</p><p>{content.limits}</p>{user.read_only && <p className="help-read-only" role="status">Tu cuenta está suspendida: puedes consultar, pero no ejecutar las acciones de modificación descritas en esta guía.</p>}</Card>
    <HelpWorkflow content={content} go={go}/>
    {content.photos && <Card title="Cómo preparar las fotos" className="help-photos"><ul><li>Fotografía de frente, con buena luz y sin movimiento. Evita reflejos y objetos que tapen los productos.</li><li>Para una góndola larga, toma fotos consecutivas con algo de traslape y ordénalas de izquierda a derecha.</li><li>Comprueba que las etiquetas y los productos se vean legibles. Puedes quitar o reordenar las fotos antes de enviar.</li><li>El ancho de la góndola es opcional y se ingresa en metros. La disponibilidad del modelo se informa en Escanear góndola.</li></ul></Card>}
    <HelpTopics content={content} go={go}/>
    <SupportChecklist/>
  </section>;
}
