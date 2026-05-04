<script setup>
defineProps({
    data: { type: Object, required: true },
})
</script>

<template>
    <div>
        <h3 class="text-sm font-bold text-[#1e293b] mb-3 px-2">Resultados</h3>
        <div class="overflow-x-auto border border-[#e2e8f0] rounded-lg">
            <table class="w-full">
                <thead>
                    <tr class="bg-[rgba(248,250,252,0.5)]">
                        <th
                            v-for="c in data.column_labels"
                            :key="c"
                            class="px-6 py-4 text-left text-xs font-semibold text-[#64748b] uppercase tracking-wide whitespace-nowrap"
                        >
                            {{ c }}
                        </th>
                    </tr>
                </thead>
                <tbody>
                    <tr
                        v-for="(row, ri) in data.rows"
                        :key="ri"
                        class="border-t border-[#f1f5f9] hover:bg-[#f8fafc] transition-colors"
                    >
                        <td
                            v-for="(cell, ci) in row"
                            :key="ci"
                            class="px-6 py-4 text-sm whitespace-nowrap"
                            :class="typeof cell === 'number'
                                ? 'font-mono text-[#475569]'
                                : 'text-[#1e293b] font-medium'"
                        >
                            {{ cell ?? '' }}
                        </td>
                    </tr>
                </tbody>
            </table>
        </div>
    </div>
</template>
