import { memo } from 'react';
import type { PersonalitySettings } from '../hooks/usePersonality';
import { NeonSlider } from './NeonSlider';
import styles from './PersonalitySliderItem.module.css';

// ── Parameter icons ───────────────────────────────────────────────────────────

function IconWarmth()     { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M12 21.593c-5.63-5.539-11-10.297-11-14.402C1 3.534 3.938 1 7 1c1.961 0 3.815.83 5 2.18C13.185 1.83 15.04 1 17 1c3.062 0 6 2.534 6 6.191 0 4.105-5.37 8.863-11 14.402z"/></svg>; }
function IconEmpathy()    { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>; }
function IconDirectness() { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/></svg>; }
function IconAssertiveness(){ return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>; }
function IconIndependence(){ return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>; }
function IconSkepticism() { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/><line x1="3" y1="3" x2="21" y2="21"/></svg>; }
function IconPatience()   { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M5 3h14"/><path d="m17 3-5 9-5-9"/><path d="M5 21h14"/><path d="m7 21 5-9 5 9"/></svg>; }
function IconCuriosity()  { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/><line x1="11" y1="8" x2="11" y2="11"/><line x1="11" y1="14" x2="11.01" y2="14"/></svg>; }
function IconProactivity(){ return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>; }
function IconHelpfulness(){ return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>; }
function IconHonesty()    { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>; }
function IconPlayfulness(){ return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M14.5 10c-.83 0-1.5-.67-1.5-1.5v-5c0-.83.67-1.5 1.5-1.5s1.5.67 1.5 1.5v5c0 .83-.67 1.5-1.5 1.5z"/><path d="M20.5 10H19V8.5c0-.83.67-1.5 1.5-1.5s1.5.67 1.5 1.5-.67 1.5-1.5 1.5z"/><path d="M9.5 14c.83 0 1.5.67 1.5 1.5v5c0 .83-.67 1.5-1.5 1.5S8 21.33 8 20.5v-5c0-.83.67-1.5 1.5-1.5z"/><path d="M3.5 14H5v1.5c0 .83-.67 1.5-1.5 1.5S2 16.33 2 15.5 2.67 14 3.5 14z"/><path d="M14 14.5c0-.83.67-1.5 1.5-1.5h5c.83 0 1.5.67 1.5 1.5s-.67 1.5-1.5 1.5h-5c-.83 0-1.5-.67-1.5-1.5z"/><path d="M15.5 19H14v1.5c0 .83.67 1.5 1.5 1.5s1.5-.67 1.5-1.5-.67-1.5-1.5-1.5z"/><path d="M10 9.5C10 8.67 9.33 8 8.5 8h-5C2.67 8 2 8.67 2 9.5S2.67 11 3.5 11h5c.83 0 1.5-.67 1.5-1.5z"/><path d="M8.5 5H10V3.5C10 2.67 9.33 2 8.5 2S7 2.67 7 3.5 7.67 5 8.5 5z"/></svg>; }
function IconStability()  { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>; }

type K = keyof PersonalitySettings;

interface ParamMeta {
  jp: string;
  es: string;
  Icon: React.FC;
  tooltip: string;
}

export const PARAM_META: Record<K, ParamMeta> = {
  warmth:              { jp: '温かさ',  es: 'Calidez',       Icon: IconWarmth,       tooltip: 'Calidez afectiva en las respuestas. Alto = cercanía y cuidado visibles; bajo = trato neutro y distante.' },
  empathy:             { jp: '共感',    es: 'Empatía',        Icon: IconEmpathy,      tooltip: 'Capacidad de reconocer y reflejar el estado emocional del interlocutor. Alto = respuestas emocionalmente resonantes.' },
  directness:          { jp: '率直',    es: 'Franqueza',      Icon: IconDirectness,   tooltip: 'Qué tan directa y sin rodeos es en sus respuestas. Alto = va al grano sin suavizar; bajo = más diplomática.' },
  assertiveness:       { jp: '主張',    es: 'Asertividad',    Icon: IconAssertiveness,tooltip: 'Confianza al expresar y defender opiniones propias. Alto = expresa posturas con firmeza; bajo = más tentativa.' },
  independence:        { jp: '独立',    es: 'Independencia',  Icon: IconIndependence, tooltip: 'Tendencia a llegar a conclusiones propias en vez de seguir al interlocutor. Alto = pensamiento propio marcado.' },
  skepticism:          { jp: '懐疑',    es: 'Escepticismo',   Icon: IconSkepticism,   tooltip: 'Propensión a cuestionar afirmaciones y pedir evidencia. Alto = recibe casi todo con suspicacia.' },
  patience:            { jp: '忍耐',    es: 'Paciencia',      Icon: IconPatience,     tooltip: 'Tolerancia ante preguntas repetidas o conversaciones lentas. Bajo = respuestas más cortas e impacientes.' },
  curiosity:           { jp: '好奇心',  es: 'Curiosidad',     Icon: IconCuriosity,    tooltip: 'Propensión a hacer preguntas de seguimiento e indagar más. Alto = muchas preguntas; bajo = responde lo justo.' },
  proactivity:         { jp: '積極性',  es: 'Proactividad',   Icon: IconProactivity,  tooltip: 'Tendencia a ofrecer ideas o información sin que se lo pidan. Bajo = solo responde lo preguntado.' },
  helpfulness:         { jp: '親切',    es: 'Ayuda',          Icon: IconHelpfulness,  tooltip: 'Cuánto esfuerzo pone en ser útil. Bajo = mínimo indispensable; alto = elabora, propone y anticipa.' },
  honesty:             { jp: '正直',    es: 'Honestidad',     Icon: IconHonesty,      tooltip: 'Qué tan directa es al decir cosas incómodas. Alto = honestidad brutal sin rodeos; bajo = respuestas suavizadas.' },
  playfulness:         { jp: 'ユーモア', es: 'Juego',         Icon: IconPlayfulness,  tooltip: 'Humor, ingenio y desenfado en las respuestas. Alto = frecuentes guiños irónicos y absurdos; bajo = tono más serio.' },
  emotional_stability: { jp: '安定',    es: 'Estabilidad',    Icon: IconStability,    tooltip: 'Consistencia emocional y compostura. Alto = reacciones moderadas y predecibles; bajo = mayor variabilidad emocional.' },
};

// ── Slider item ───────────────────────────────────────────────────────────────

interface PersonalitySliderItemProps {
  paramKey: K;
  value: number; // 0–1
  onDrag: (v: number) => void;
  onCommit: (v: number) => void;
}

export const PersonalitySliderItem = memo(function PersonalitySliderItem({
  paramKey, value, onDrag, onCommit,
}: PersonalitySliderItemProps) {
  const { jp, es, Icon, tooltip } = PARAM_META[paramKey];
  const pct = Math.round(value * 100);

  return (
    <div className={styles.row}>
      <span className={styles.icon}><Icon /></span>

      <div className={styles.names}>
        <span className={styles.nameEs} title={tooltip}>{es}</span>
        <span className={styles.nameJp}>{jp}</span>
      </div>

      <div className={styles.sliderWrap}>
        <NeonSlider value={value} onChange={onDrag} onCommit={onCommit} />
      </div>

      <span className={styles.pct}>{pct}%</span>
    </div>
  );
});
