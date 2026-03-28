import type { ButtonHTMLAttributes } from 'react';
import { cn } from '../../lib/utils';

const variants = {
  default: 'bg-cyan-400/90 text-slate-950 hover:bg-cyan-300',
  ghost: 'bg-transparent text-slate-300 hover:bg-white/5 hover:text-white',
  outline: 'border border-white/10 bg-white/5 text-white hover:bg-white/10',
};

export function Button({
  className,
  variant = 'default',
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: keyof typeof variants }) {
  return (
    <button
      className={cn(
        'inline-flex items-center justify-center rounded-2xl px-4 py-2 text-sm font-medium transition focus:outline-none focus:ring-2 focus:ring-cyan-400/60 disabled:pointer-events-none disabled:opacity-50',
        variants[variant],
        className,
      )}
      {...props}
    />
  );
}
