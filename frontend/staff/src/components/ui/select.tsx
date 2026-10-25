import { cn } from '../../lib/utils';

type SelectProps = React.SelectHTMLAttributes<HTMLSelectElement>;

export function Select({ className, ...props }: SelectProps) {
  return (
    <select
      className={cn(
        'rounded-lg border border-border-strong bg-surface-sunken px-3 py-2 text-primary',
        'focus:outline-none focus:ring-2 focus:ring-focus-ring focus:border-transparent',
        className
      )}
      {...props}
    />
  );
}
