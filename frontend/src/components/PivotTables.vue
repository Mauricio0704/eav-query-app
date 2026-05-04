<script setup>
defineProps({
    data: { type: Object, required: true },
});

function isNumeric(cell, i) {
    return typeof cell === "number" && i >= 2;
}

function isTotalRow(row) {
    return row[0] === "Total";
}
</script>

<template>
    <!-- Valores Absolutos -->
    <div>
        <h3 class="text-sm font-bold text-[#1e293b] mb-3 px-2">
            Valores Absolutos
        </h3>
        <div class="overflow-x-auto border border-[#e2e8f0] rounded-lg">
            <table class="w-full">
                <thead>
                    <tr class="bg-[rgba(248,250,252,0.5)]">
                        <th
                            v-for="c in data.counts.columns"
                            :key="c"
                            class="px-6 py-4 text-left text-xs font-semibold text-[#64748b] uppercase tracking-wide whitespace-nowrap"
                        >
                            {{ c }}
                        </th>
                    </tr>
                </thead>
                <tbody>
                    <tr
                        v-for="(row, ri) in data.counts.rows"
                        :key="ri"
                        :class="
                            isTotalRow(row)
                                ? 'bg-[rgba(248,250,252,0.3)] border-t-2 border-[#e2e8f0]'
                                : 'border-t border-[#f1f5f9] hover:bg-[#f8fafc] transition-colors'
                        "
                    >
                        <td
                            v-for="(cell, ci) in row"
                            :key="ci"
                            class="px-6 py-4 text-sm whitespace-nowrap"
                            :class="
                                isTotalRow(row)
                                    ? 'font-bold text-[#0f172a]'
                                    : isNumeric(cell, ci)
                                      ? 'font-mono text-[#475569]'
                                      : 'text-[#1e293b] font-medium'
                            "
                        >
                            {{ cell === "" || cell == null ? "" : cell }}
                        </td>
                    </tr>
                </tbody>
            </table>
        </div>
    </div>

    <!-- Valores Relativos -->
    <div>
        <h3 class="text-sm font-bold text-[#1e293b] mb-3 px-2">
            Valores Relativos
        </h3>
        <div class="overflow-x-auto border border-[#e2e8f0] rounded-lg">
            <table class="w-full">
                <thead>
                    <tr class="bg-[rgba(248,250,252,0.5)]">
                        <th
                            v-for="c in data.percentages.columns"
                            :key="c"
                            class="px-6 py-4 text-left text-xs font-semibold text-[#64748b] uppercase tracking-wide whitespace-nowrap"
                        >
                            {{ c }}
                        </th>
                    </tr>
                </thead>
                <tbody>
                    <tr
                        v-for="(row, ri) in data.percentages.rows"
                        :key="ri"
                        :class="
                            isTotalRow(row)
                                ? 'bg-[rgba(248,250,252,0.3)] border-t-2 border-[#e2e8f0]'
                                : 'border-t border-[#f1f5f9] hover:bg-[#f8fafc] transition-colors'
                        "
                    >
                        <td
                            v-for="(cell, ci) in row"
                            :key="ci"
                            class="px-6 py-4 text-sm whitespace-nowrap"
                            :class="
                                isTotalRow(row)
                                    ? 'font-bold text-[#0f172a]'
                                    : isNumeric(cell, ci)
                                      ? 'font-mono text-[#475569]'
                                      : 'text-[#1e293b] font-medium'
                            "
                        >
                            {{ cell === "" || cell == null ? "" : cell }}
                        </td>
                    </tr>
                </tbody>
            </table>
        </div>
    </div>
</template>
