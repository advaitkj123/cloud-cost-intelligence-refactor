import type { HTMLAttributes } from 'react';
import { cn } from '../../lib/utils';

const variants = {
  default: 'border-white/10 bg-white/5 text-slate-200',
  success: 'border-emerald-500/20 bg-emerald-500/10 text-emerald-300',
  warning: 'border-amber-500/20 bg-amber-500/10 text-amber-300',
  danger: 'border-rose-500/20 bg-rose-500/10 text-rose-300',
  info: 'border-cyan-500/20 bg-cyan-500/10 text-cyan-300',
};

export function Badge({
  className,
  variant = 'default',
  ...props
}: HTMLAttributes<HTMLSpanElement> & { variant?: keyof typeof variants }) {
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-medium uppercase tracking-[0.16em]',
        variants[variant],
        className,
      )}
      {...props}
    />
  );
}
