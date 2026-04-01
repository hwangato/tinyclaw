interface Change {
  dimension: string;
  before: string;
  after: string;
}

interface ChangesTableProps {
  changes: Change[];
}

export function ChangesTable({ changes }: ChangesTableProps) {
  return (
    <div className="overflow-x-auto my-4">
      <table className="w-full text-sm border-collapse">
        <thead>
          <tr className="border-b-2 border-zinc-200 dark:border-zinc-700">
            <th className="text-left py-3 px-4 font-semibold text-zinc-700 dark:text-zinc-300">
              维度
            </th>
            <th className="text-left py-3 px-4 font-semibold text-zinc-700 dark:text-zinc-300">
              之前
            </th>
            <th className="text-left py-3 px-4 font-semibold text-zinc-700 dark:text-zinc-300">
              之后
            </th>
          </tr>
        </thead>
        <tbody>
          {changes.map((change, i) => (
            <tr
              key={i}
              className="border-b border-zinc-100 dark:border-zinc-800 hover:bg-zinc-50 dark:hover:bg-zinc-800/50 transition-colors"
            >
              <td className="py-3 px-4 font-medium text-zinc-800 dark:text-zinc-200">
                {change.dimension}
              </td>
              <td className="py-3 px-4 text-zinc-500 dark:text-zinc-400">
                {change.before}
              </td>
              <td className="py-3 px-4 text-emerald-600 dark:text-emerald-400 font-medium">
                {change.after}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
