'use client';

function Line({short = false, tall = false}) {
  return <span className={`home-skeleton-line${short ? ' short' : ''}${tall ? ' tall' : ''}`}/>;
}

export default function HomeSkeleton({fullPage = false, role}) {
  const content = <>
    {fullPage && <div className="home-skeleton-heading"><Line short/><Line tall/><Line/></div>}
    <div className="home-skeleton-cards" aria-hidden="true">
      {Array.from({length: role === 'admin' ? 6 : 3}, (_, index) => <div className="home-skeleton-card" key={index}><Line short/><Line tall/><Line/></div>)}
    </div>
    {role !== 'admin' && <div className="home-skeleton-panels" aria-hidden="true">
      {[0, 1].map(index => <div className="home-skeleton-card" key={index}><Line short/>{[0, 1, 2].map(row => <div className="home-skeleton-row" key={row}><Line/><Line short/><Line short/></div>)}</div>)}
    </div>}
  </>;
  return <div className={fullPage ? 'home-entry-skeleton' : 'home-content-skeleton'} role="status" aria-label="Cargando Inicio" aria-busy="true">
    <span className="home-skeleton-sr">Cargando Inicio…</span>
    {fullPage ? <>
      <aside className="home-skeleton-sidebar" aria-hidden="true"><Line short/><div className="home-skeleton-avatar"/>{Array.from({length: 7}, (_, index) => <Line key={index}/>)}</aside>
      <div className="home-skeleton-main"><div className="home-skeleton-topbar" aria-hidden="true"><Line short/></div><div className="home-skeleton-page" aria-hidden="true">{content}</div></div>
    </> : content}
  </div>;
}
