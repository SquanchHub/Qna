import { cn } from '../../lib/utils';

type SelectProps = React.SelectHTMLAttributes<HTMLSelectElement>;

export function Select({ className, ...props }: SelectProps) {
  return (
    <select
      className={cn(
        'rounded-lg border border-slate-600 bg-slate-800 px-3 py-2 text-slate-100',
        'focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent',
        className
      )}
      {...props}
    />
  );
}
