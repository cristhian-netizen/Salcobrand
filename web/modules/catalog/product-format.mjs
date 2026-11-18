export const DISPLAY_TYPES = ['Individual','Pack 2x','Pack 3x','Pack 4x','Pack 5x'];
export const unitPrice = product => product.price == null ? null : product.price * (product.saleUnit === 'unidad' ? 1 : 1000) / product.quantity;
export const priceUnit = saleUnit => saleUnit === 'unidad' ? 'unidad' : saleUnit === 'ml' ? 'litro' : 'kg';
