export type StudentProfile = {
  student_id: string;
  name: string;
  gpa: number;
  allowed_hours: number;
  status: string;
  faculty?: string | null;
};

export type FeeBreakdown = {
  student_id: string;
  base_tuition: number;
  fixed_fee: number;
  late_penalty?: number;
  scholarship_discount?: number;
  total: number;
  currency: string;
  line_items: { label: string; amount: number }[];
};

export type PaymentItem = {
  transaction_id: string;
  student_id: string;
  student_name: string;
  amount: string;
  status: string;
  payment_method?: string | null;
  semester: string;
  gateway_reference?: string | null;
  created_at: string;
  updated_at?: string;
};

export type PaymentDetail = {
  transaction_id: string;
  amount: string;
  status: string;
  payment_method?: string | null;
  semester: string;
  gateway_reference?: string | null;
  created_at: string;
  updated_at: string;
};

export type AdminPaymentSummary = {
  total_count: number;
  status_counts: Record<string, number>;
  total_paid_amount: string;
};

export type AdminPaymentListResponse = {
  total_records: number;
  page: number;
  page_size: number;
  payments: PaymentItem[];
};

export type AdminPaymentAuditLog = {
  id: number;
  event_type: string;
  amount: string | null;
  actor: string | null;
  payload: Record<string, unknown> | null;
  created_at: string;
};

export type AdminPaymentDetail = {
  transaction_id: string;
  student_id: string;
  student_name: string;
  amount: string;
  status: string;
  payment_method?: string | null;
  semester: string;
  used: boolean;
  gateway_reference?: string | null;
  expires_at?: string | null;
  created_at: string;
  updated_at: string;
  audit_logs: AdminPaymentAuditLog[];
};
