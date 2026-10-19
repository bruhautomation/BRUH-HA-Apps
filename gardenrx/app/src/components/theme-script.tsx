import type { ThemeMode } from '@/lib/settings';

/**
 * Pre-paint script that resolves the "auto" theme against the OS color scheme
 * and keeps it in sync live. For explicit modes the server already set
 * `data-theme`, so this is a no-op beyond wiring the media listener.
 *
 * Rendered as the first child of <body> so it runs before content paints.
 */
export function ThemeScript({ mode }: { mode: ThemeMode }) {
  const js = `(function(){try{
    var root=document.documentElement;
    var mode=${JSON.stringify(mode)};
    var mq=window.matchMedia('(prefers-color-scheme: dark)');
    function apply(){ if(root.getAttribute('data-theme-mode')==='auto'){ root.setAttribute('data-theme', mq.matches?'dark':'light'); } }
    root.setAttribute('data-theme-mode', mode);
    apply();
    mq.addEventListener('change', apply);
  }catch(e){}})();`;
  return <script dangerouslySetInnerHTML={{ __html: js }} />;
}
