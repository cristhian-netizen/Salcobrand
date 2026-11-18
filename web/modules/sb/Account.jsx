'use client';
import {PASSWORD_PATTERN, PASSWORD_HELP} from '../../lib/password-policy.mjs';
import {useState} from 'react';
import {auth, ROLE_NAMES} from '../../lib/sb';
import {Header, Card} from './ui';

export default function Account({user, notify}) {
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  async function submit(e) {
    e.preventDefault(); setError('');
    const f = new FormData(e.currentTarget);
    if (f.get('new_password') !== f.get('confirm')) { setError('Las contraseñas nuevas no coinciden.'); return; }
    setBusy(true);
    try { await auth.changePassword(f.get('current_password'), f.get('new_password')); e.target.reset(); notify('Contraseña actualizada.'); }
    catch (err) { setError(err.message); } finally { setBusy(false); }
  }
  return <section>
    <Header eyebrow="Administración" title="Mi cuenta" subtitle={`${user.username} · ${ROLE_NAMES[user.role] || user.role}${user.store_id ? ` · ${user.store_name || user.store_id}` : ''}`}/>
    <Card title="Cambiar contraseña" subtitle={PASSWORD_HELP}>
      {error && <div className="sb-error" role="alert">{error}</div>}
      <form className="sb-form" onSubmit={submit}>
        <label className="full">Contraseña actual<input name="current_password" type="password" required autoComplete="current-password"/></label>
        <label>Nueva contraseña<input name="new_password" type="password" required minLength={8} maxLength={512} pattern={PASSWORD_PATTERN} title={PASSWORD_HELP} autoComplete="new-password"/></label>
        <label>Repite la nueva contraseña<input name="confirm" type="password" required minLength={8} maxLength={512} pattern={PASSWORD_PATTERN} title={PASSWORD_HELP} autoComplete="new-password"/></label>
        <div className="sb-actions"><button disabled={busy || user.read_only}>{busy ? 'Guardando…' : 'Actualizar contraseña'}</button></div>
      </form>
    </Card>
  </section>;
}
