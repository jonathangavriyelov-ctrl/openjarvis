import { useState } from 'react';
import './HelpTip.css';

export function HelpTip({ text, above = false }: { text: string; above?: boolean }) {
  const [open, setOpen] = useState(false);
  const className = [
    'help-tip',
    open ? 'is-open' : '',
    above ? 'is-above' : '',
  ].filter(Boolean).join(' ');
  return (
    <span
      className={className}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      <button
        type="button"
        className="help-tip-btn"
        aria-label={text}
        aria-expanded={open}
        onClick={(event) => {
          event.preventDefault();
          event.stopPropagation();
          setOpen((value) => !value);
        }}
      >
        ?
      </button>
      <span className="help-tip-bubble" role="tooltip">
        {text}
      </span>
    </span>
  );
}
