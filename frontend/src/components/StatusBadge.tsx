import clsx from 'clsx';

export function StatusBadge({ status }: { status: string }) {
  return (
    <span
      className={clsx(
        'inline-flex rounded-full px-3 py-1 text-xs font-medium capitalize',
        status === 'running' || status === 'active'
          ? 'bg-emerald-500/15 text-emerald-300'
          : status === 'stopped'
            ? 'bg-red-500/15 text-red-300'
            : 'bg-amber-500/15 text-amber-300'
      )}
    >
      {status}
    </span>
  );
}
