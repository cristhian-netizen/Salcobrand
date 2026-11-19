'use client';

import {useState} from 'react';
import styled from '@emotion/styled';

/* Salcobrand palette (salcobrand.cl): institutional blue #0074c8, deep blue #0051b3,
   action blue #06a7e2, logo-leaf yellow #feca42. Text keeps WCAG AA on each surface. */

const Screen = styled.div`
  min-height: 100vh;
  min-height: 100dvh;
  display: grid;
  grid-template-columns: minmax(360px, 46%) minmax(0, 1fr);
  background: #ffffff;
  color: #333333;
  font-family: var(--nv-font);
  @media (max-width: 800px) { grid-template-columns: 1fr; }
`;

const Brand = styled.aside`
  position: relative;
  isolation: isolate;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  min-height: 100vh;
  min-height: 100dvh;
  padding: clamp(32px, 5vw, 76px);
  color: #ffffff;
  background: radial-gradient(circle at 80% 76%, #06a7e233, transparent 45%), #0051b3;
  &::after {
    content: '';
    position: absolute;
    z-index: -1;
    width: min(70vw, 680px);
    aspect-ratio: 1;
    right: -35%;
    bottom: -40%;
    border: 1px solid #ffffff35;
    border-radius: 50%;
    box-shadow: 0 0 0 70px #ffffff0c, 0 0 0 140px #ffffff08;
  }
  @media (max-width: 800px) { display: none; }
`;

const BrandName = styled.span`
  display: inline-flex;
  align-items: center;
  gap: 12px;
  font-size: 19px;
  font-weight: 700;
  letter-spacing: -.045em;
`;

const Mark = styled.img`
  display: block;
  flex: none;
  width: 38px;
  height: 38px;
  padding: 2px;
  border-radius: 50%;
  background: #ffffff;
  object-fit: contain;
`;

const BrandCopy = styled.div`
  max-width: 540px;
  margin: auto 0;
  span { color: #feca42; font-size: 12px; font-weight: 700; letter-spacing: .15em; text-transform: uppercase; }
  h2 { margin: 22px 0 20px; font-size: clamp(43px, 4.4vw, 70px); font-weight: 600; line-height: 1.08; letter-spacing: -.065em; }
  p { max-width: 440px; color: #cfe7ff; font-size: 17px; line-height: 1.7; }
`;

const SignInArea = styled.main`
  display: flex;
  flex-direction: column;
  min-height: 100vh;
  min-height: 100dvh;
  padding: clamp(24px, 4vw, 64px);
  background: #ffffff;
`;

const MobileBrand = styled.div`
  display: none;
  color: #0074c8;
  @media (max-width: 800px) { display: block; }
`;

const FormWrap = styled.div`
  width: min(100%, 420px);
  margin: auto;
  padding: 44px 0;
  .eyebrow { color: #0074c8; font-size: 12px; font-weight: 750; letter-spacing: .13em; text-transform: uppercase; }
  h1 { margin: 14px 0 12px; color: #101828; font-size: clamp(34px, 3vw, 43px); font-weight: 650; line-height: 1.14; letter-spacing: -.06em; }
  .intro { margin: 0 0 40px; color: #5d6875; font-size: 15px; line-height: 1.6; }
  label { display: block; margin: 0 0 20px; color: #344054; font-size: 13px; font-weight: 650; }
  input { display: block; width: 100%; height: 54px; margin-top: 9px; padding: 0 16px; border: 1px solid #d0d5dd; border-radius: 12px; outline: none; background: #ffffff; color: #101828; font: inherit; font-size: 15px; transition: border-color .18s, box-shadow .18s; }
  input::placeholder { color: #98a2b3; }
  input:focus { border-color: #0074c8; box-shadow: 0 0 0 4px #0074c829; }
  .password-field { position: relative; display: block; }
  .password-label { margin-bottom: 9px; }
  .password-field input { margin-top: 0; padding-right: 88px; }
  .show-password { position: absolute; right: 10px; top: 16px; padding: 5px 8px; border: 0; background: transparent; color: #0074c8; font: inherit; font-size: 13px; font-weight: 700; cursor: pointer; }
  .show-password:hover { color: #0051b3; }
  .error { margin: 0 0 18px; padding: 12px 14px; border: 1px solid #f0c9c4; border-radius: 10px; background: #fff1ef; color: #9d3127; font-size: 14px; line-height: 1.5; }
  .submit { display: flex; align-items: center; justify-content: center; gap: 12px; width: 100%; min-height: 54px; margin-top: 30px; border: 0; border-radius: 12px; background: linear-gradient(110deg, #0051b3, #0074c8); color: #ffffff; font: inherit; font-size: 15px; font-weight: 700; cursor: pointer; box-shadow: 0 10px 22px #0074c829; transition: background .18s, transform .18s, box-shadow .18s; }
  .submit:hover:not(:disabled) { background: #0051b3; transform: translateY(-2px); box-shadow: 0 14px 25px #0074c838; }
  .submit:disabled { cursor: wait; opacity: .7; }
  .submit span { font-size: 21px; font-weight: 400; line-height: 1; }
  .footnote { margin: 24px 0 0; color: #667085; font-size: 12px; line-height: 1.6; text-align: center; }
  @media (max-width: 800px) { padding: 60px 0; }
  @media (max-width: 480px) { padding: 42px 0; .intro { margin-bottom: 34px; } }
  @media (prefers-reduced-motion: reduce) { input, .submit { transition: none; } .submit:hover:not(:disabled) { transform: none; } }
`;

const Footer = styled.footer`
  display: grid;
  gap: 2px;
  color: #667085;
  font-size: 12px;
  p { margin: 0; }
  .tech { color: #667085; font-size: 11.5px; }
  @media (max-width: 800px) { text-align: center; }
`;

export default function Login({onLogin}) {
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [showPassword, setShowPassword] = useState(false);

  async function submit(event) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError('');
    const form = new FormData(event.currentTarget);
    try {
      await onLogin(form.get('username'), form.get('password'));
    } catch (exception) {
      setError(exception?.message || 'No fue posible iniciar sesión. Inténtalo nuevamente.');
    } finally {
      setBusy(false);
    }
  }

  return <Screen>
    <Brand aria-label="Salcobrand">
      <BrandName><Mark src="/branding/salcobrand-logo.svg" alt="" aria-hidden="true"/> Salcobrand</BrandName>
      <BrandCopy>
        <span>Tu espacio de trabajo</span>
        <h2>Más claridad.<br/>Mejores decisiones.</h2>
        <p>Todo lo que necesitas para entender tu operación, en un solo lugar.</p>
      </BrandCopy>
      <small>Inteligencia para cada punto de venta.</small>
    </Brand>
    <SignInArea>
      <MobileBrand><BrandName><Mark src="/branding/salcobrand-logo.svg" alt="" aria-hidden="true"/> Salcobrand</BrandName></MobileBrand>
      <FormWrap>
        <span className="eyebrow">Bienvenido de nuevo</span>
        <h1>Inicia sesión</h1>
        <p className="intro">Accede a tu espacio de trabajo y continúa donde lo dejaste.</p>
        <form onSubmit={submit} aria-busy={busy}>
          <label htmlFor="login-username">Usuario o email
            <input id="login-username" name="username" autoComplete="username" placeholder="Tu nombre de usuario o email" required disabled={busy}/>
          </label>
          <label className="password-label" htmlFor="login-password">Contraseña</label>
          <span className="password-field">
            <input id="login-password" name="password" type={showPassword ? 'text' : 'password'} autoComplete="current-password" placeholder="Ingresa tu contraseña" required disabled={busy}/>
            <button className="show-password" type="button" onClick={() => setShowPassword(value => !value)} aria-label={showPassword ? 'Ocultar contraseña' : 'Mostrar contraseña'} aria-pressed={showPassword}>
              {showPassword ? 'Ocultar' : 'Mostrar'}
            </button>
          </span>
          {error && <p className="error" role="alert">{error}</p>}
          <button className="submit" type="submit" disabled={busy}>{busy ? 'Ingresando…' : <>Entrar al espacio <span aria-hidden="true">→</span></>}</button>
        </form>
        <p className="footnote">Acceso seguro para miembros de tu organización.</p>
      </FormWrap>
      <Footer>
        <p>© {new Date().getFullYear()} Salcobrand</p>
        <p className="tech">Con tecnología NeuraVision · Neuramorphic</p>
      </Footer>
    </SignInArea>
  </Screen>;
}
