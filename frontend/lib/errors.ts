import { ApiError } from "@/lib/api";
import type { MessageKey } from "@/lib/messages";

/** Backend error codes shown to people, in their language (deep audit: no raw English from the API). */
const CODES: Record<string, MessageKey> = {
  invalid_phone: "e_invalidPhone",
  otp_invalid: "e_otpInvalid",
  otp_expired: "e_otpExpired",
  rate_limited: "e_rateLimited",
  slug_taken: "e_slugTaken",
  slug_reserved: "e_slugReserved",
  invalid_slug: "e_invalidSlug",
  invalid_location: "e_invalidLocation",
  account_disabled: "e_accountDisabled",
  shop_exists: "e_shopExists",
  validation_error: "e_checkInput",
};

export function errorKey(e: unknown): MessageKey {
  if (!(e instanceof ApiError)) return "genericError";
  return CODES[e.code] ?? (e.status === 422 ? "e_checkInput" : "genericError");
}
