import {Card} from '../sb/ui';

export default function SupportChecklist() {
  return <Card title="¿Necesitas soporte?" className="help-support"><p>Contacta al equipo de soporte habitual de Neuramorphic. Para revisar el caso, prepara:</p><ul><li>Nombre del cliente y ambiente: localhost, desarrollo o producción.</li><li>Módulo, código del PDV y góndola afectada.</li><li>Número de medición o solicitud, si está disponible.</li><li>Fecha, hora, mensaje de error y los pasos para reproducirlo.</li><li>Una captura de pantalla sin contraseñas, claves ni datos personales innecesarios.</li></ul><p className="sb-hint">Esta página es una guía. No envía tickets ni invitaciones por correo. Las claves del modelo se configuran en el servidor por el equipo autorizado.</p><p className="sb-hint">Con tecnología NeuraVision · Neuramorphic</p></Card>;
}
