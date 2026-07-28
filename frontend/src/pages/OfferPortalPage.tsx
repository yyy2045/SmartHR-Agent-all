import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  LockOutlined,
  ReloadOutlined,
  SafetyCertificateOutlined,
  SolutionOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery } from '@tanstack/react-query'
import {
  Alert,
  Button,
  Descriptions,
  Divider,
  Form,
  Input,
  Modal,
  Result,
  Select,
  Skeleton,
  Tag,
  Typography,
  message,
} from 'antd'
import { useEffect, useRef, useState, type ReactNode } from 'react'

import {
  ApiError,
  fetchOfferPortalDetail,
  fetchOfferPortalStatus,
  respondToOfferPortal,
  type CandidateOfferDecision,
  type CandidateOfferRejectionReason,
  type CandidateOfferViewRecord,
  type OfferPortalVerifiedRecord,
  verifyOfferPortal,
} from '../api/client'

const { Title, Text, Paragraph } = Typography

interface VerificationValues {
  phoneLastFour: string
}

interface RejectionValues {
  reason: CandidateOfferRejectionReason
  note?: string
}

interface ResponseTarget {
  decision: CandidateOfferDecision
  idempotencyKey: string
}

const rejectionReasonLabels: Record<CandidateOfferRejectionReason, string> = {
  compensation: '薪资原因',
  career: '职业发展',
  location: '工作地点',
  timing: '入职时间',
  other: '其他原因',
}

function money(value: string | null) {
  if (value === null) return '不适用'
  return `${Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 2 })} 元/月`
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(new Date(`${value}T00:00:00`))
}

function formatDateTime(value: string) {
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

function annualSalary(offer: CandidateOfferViewRecord) {
  const total = Number(offer.monthly_salary) * Number(offer.annual_salary_months)
  return `${total.toLocaleString('zh-CN', { maximumFractionDigits: 2 })} 元/年`
}

function portalErrorContent(error: unknown) {
  if (!(error instanceof ApiError)) {
    return { title: '暂时无法打开页面', message: '请稍后重试', status: 'error' as const }
  }
  if (error.status === 404) {
    return { title: '链接无效', message: error.message, status: 'warning' as const }
  }
  if (error.status === 410) {
    return { title: '链接已失效', message: error.message, status: 'warning' as const }
  }
  if (error.status === 429) {
    return { title: '验证暂时锁定', message: error.message, status: 'warning' as const }
  }
  if (error.status === 503) {
    return { title: '验证服务暂不可用', message: error.message, status: 'error' as const }
  }
  return { title: '无法处理请求', message: error.message, status: 'error' as const }
}

function PortalShell({ children }: { children: ReactNode }) {
  return (
    <div className="candidate-offer-portal">
      <header className="candidate-offer-header">
        <div className="candidate-offer-brand">
          <span className="candidate-offer-brand-mark" aria-hidden="true">
            <SolutionOutlined />
          </span>
          <span>
            <Text strong>SmartHR</Text>
            <Text type="secondary">候选人服务</Text>
          </span>
        </div>
        <Text className="candidate-offer-security">
          <SafetyCertificateOutlined /> 安全访问
        </Text>
      </header>
      <main className="candidate-offer-main">{children}</main>
      <footer className="candidate-offer-footer">SmartHR 企业招聘平台</footer>
    </div>
  )
}

export function OfferPortalPage() {
  const capturedToken = useRef(false)
  const [verificationForm] = Form.useForm<VerificationValues>()
  const [rejectionForm] = Form.useForm<RejectionValues>()
  const [messageApi, messageContext] = message.useMessage()
  const [token, setToken] = useState('')
  const [tokenReady, setTokenReady] = useState(false)
  const [verification, setVerification] = useState<{
    token: string
    expiresAt: string
  }>()
  const [offer, setOffer] = useState<CandidateOfferViewRecord>()
  const [responseTarget, setResponseTarget] = useState<ResponseTarget>()
  const [terminalError, setTerminalError] = useState<unknown>()

  useEffect(() => {
    if (capturedToken.current) return
    capturedToken.current = true
    const fragment = window.location.hash.startsWith('#')
      ? window.location.hash.slice(1).trim()
      : ''
    window.history.replaceState(
      window.history.state,
      '',
      `${window.location.pathname}${window.location.search}`,
    )
    setToken(fragment)
    setTokenReady(true)
  }, [])

  const statusQuery = useQuery({
    queryKey: ['candidate-offer-portal-status'],
    queryFn: () => fetchOfferPortalStatus(token),
    enabled: tokenReady && Boolean(token),
    retry: false,
  })

  const verifyMutation = useMutation({
    mutationFn: (values: VerificationValues) =>
      verifyOfferPortal(token, values.phoneLastFour),
    onSuccess: (verified: OfferPortalVerifiedRecord) => {
      setVerification({
        token: verified.verification_token,
        expiresAt: verified.verification_expires_at,
      })
      setOffer(verified)
      setTerminalError(undefined)
    },
    onError: (error) => {
      if (error instanceof ApiError && [404, 410].includes(error.status)) {
        setTerminalError(error)
      }
    },
  })

  const responseMutation = useMutation({
    mutationFn: async ({
      target,
      rejection,
    }: {
      target: ResponseTarget
      rejection?: RejectionValues
    }) => {
      if (!verification) throw new Error('候选人验证已失效')
      return respondToOfferPortal(
        token,
        verification.token,
        target.decision,
        rejection?.reason ?? null,
        rejection?.note?.trim() || null,
        target.idempotencyKey,
      )
    },
    onSuccess: (saved, variables) => {
      setOffer(saved)
      if (variables.target.decision === 'rejected') rejectionForm.resetFields()
      setResponseTarget(undefined)
      void messageApi.success(saved.progress === 'accepted' ? '已接受 Offer' : '已提交拒绝回应')
    },
    onError: async (error) => {
      if (error instanceof ApiError && [404, 410].includes(error.status)) {
        setTerminalError(error)
        setResponseTarget(undefined)
        return
      }
      if (error instanceof ApiError && error.status === 401) {
        setOffer(undefined)
        setVerification(undefined)
        setResponseTarget(undefined)
        void messageApi.warning('身份验证已失效，请重新验证')
        return
      }
      if (error instanceof ApiError && error.status === 409 && verification) {
        try {
          const current = await fetchOfferPortalDetail(token, verification.token)
          setOffer(current)
          setResponseTarget(undefined)
          void messageApi.warning('Offer 状态已由其他操作更新')
        } catch {
          // Keep the original conflict visible in the confirmation dialog.
        }
      }
    },
  })

  function openResponse(decision: CandidateOfferDecision) {
    setResponseTarget({ decision, idempotencyKey: crypto.randomUUID() })
  }

  function submitResponse() {
    if (!responseTarget) return
    if (responseTarget.decision === 'accepted') {
      responseMutation.mutate({ target: responseTarget })
      return
    }
    void rejectionForm.validateFields().then((rejection) => {
      responseMutation.mutate({ target: responseTarget, rejection })
    })
  }

  if (!tokenReady) {
    return (
      <PortalShell>
        <section className="candidate-offer-panel">
          <Skeleton active paragraph={{ rows: 5 }} />
        </section>
      </PortalShell>
    )
  }

  if (!token) {
    return (
      <PortalShell>
        <section className="candidate-offer-panel">
          <Result status="warning" title="链接不完整" subTitle="请使用招聘专员提供的完整链接。" />
        </section>
      </PortalShell>
    )
  }

  const blockingError = terminalError ?? statusQuery.error
  if (blockingError) {
    const content = portalErrorContent(blockingError)
    return (
      <PortalShell>
        <section className="candidate-offer-panel">
          <Result
            status={content.status}
            title={content.title}
            subTitle={content.message}
            extra={
              blockingError instanceof ApiError && blockingError.status === 503 ? (
                <Button icon={<ReloadOutlined />} onClick={() => void statusQuery.refetch()}>
                  重新加载
                </Button>
              ) : undefined
            }
          />
        </section>
      </PortalShell>
    )
  }

  if (statusQuery.isPending || !statusQuery.data) {
    return (
      <PortalShell>
        <section className="candidate-offer-panel">
          <Skeleton active paragraph={{ rows: 6 }} />
        </section>
      </PortalShell>
    )
  }

  if (!offer || !verification) {
    const verifyError = verifyMutation.error
      ? portalErrorContent(verifyMutation.error)
      : undefined
    return (
      <PortalShell>
        {messageContext}
        <section className="candidate-offer-panel candidate-offer-verification" aria-labelledby="offer-verify-title">
          <span className="candidate-offer-lock" aria-hidden="true">
            <LockOutlined />
          </span>
          <Title level={2} id="offer-verify-title">验证身份</Title>
          <Text type="secondary">输入手机号码后四位</Text>
          {verifyError && (
            <Alert
              type={verifyMutation.error instanceof ApiError && verifyMutation.error.status === 503 ? 'error' : 'warning'}
              showIcon
              message={verifyError.title}
              description={verifyError.message}
            />
          )}
          <Form<VerificationValues>
            form={verificationForm}
            layout="vertical"
            requiredMark={false}
            onFinish={(values) => verifyMutation.mutate(values)}
          >
            <Form.Item
              label="手机号后四位"
              name="phoneLastFour"
              rules={[
                { required: true, message: '请输入手机号后四位' },
                { pattern: /^\d{4}$/, message: '请输入 4 位数字' },
              ]}
            >
              <Input
                size="large"
                inputMode="numeric"
                autoComplete="one-time-code"
                maxLength={4}
                placeholder="0000"
              />
            </Form.Item>
            <Button
              type="primary"
              size="large"
              htmlType="submit"
              loading={verifyMutation.isPending}
              block
            >
              验证并查看 Offer
            </Button>
          </Form>
        </section>
      </PortalShell>
    )
  }

  const response = offer.response
  return (
    <PortalShell>
      {messageContext}
      <section className="candidate-offer-panel candidate-offer-document" aria-labelledby="candidate-offer-title">
        <div className="candidate-offer-title-row">
          <div>
            <Text type="secondary">{offer.candidate_name || '候选人'}，您好</Text>
            <Title level={2} id="candidate-offer-title">{offer.job_title}</Title>
          </div>
          <Tag color={offer.progress === 'offer_pending_response' ? 'processing' : offer.progress === 'accepted' ? 'success' : 'error'}>
            {offer.progress === 'offer_pending_response'
              ? '待回应'
              : offer.progress === 'accepted'
                ? '已接受'
                : '已拒绝'}
          </Tag>
        </div>

        <Descriptions column={{ xs: 1, sm: 2 }} bordered size="small">
          <Descriptions.Item label="月薪">{money(offer.monthly_salary)}</Descriptions.Item>
          <Descriptions.Item label="年薪月数">{Number(offer.annual_salary_months)} 薪</Descriptions.Item>
          <Descriptions.Item label="参考年薪" span={{ xs: 1, sm: 2 }}>{annualSalary(offer)}</Descriptions.Item>
          <Descriptions.Item label="试用期">{offer.probation_months ? `${offer.probation_months} 个月` : '无'}</Descriptions.Item>
          <Descriptions.Item label="试用期月薪">{money(offer.probation_monthly_salary)}</Descriptions.Item>
          <Descriptions.Item label="Offer 有效期">{formatDate(offer.valid_until)}</Descriptions.Item>
          <Descriptions.Item label="预计入职日">{formatDate(offer.expected_start_date)}</Descriptions.Item>
          <Descriptions.Item label="奖金说明" span={{ xs: 1, sm: 2 }}>{offer.bonus_description || '未填写'}</Descriptions.Item>
          <Descriptions.Item label="Offer 备注" span={{ xs: 1, sm: 2 }}>{offer.notes || '未填写'}</Descriptions.Item>
        </Descriptions>

        {response ? (
          <div className={`candidate-offer-response candidate-offer-response--${response.decision}`}>
            {response.decision === 'accepted' ? <CheckCircleOutlined /> : <CloseCircleOutlined />}
            <div>
              <Title level={4}>{response.decision === 'accepted' ? '您已接受 Offer' : '您已拒绝 Offer'}</Title>
              <Text type="secondary">回应时间：{formatDateTime(response.responded_at)}</Text>
              {response.rejection_reason_code && (
                <Paragraph>拒绝原因：{rejectionReasonLabels[response.rejection_reason_code]}</Paragraph>
              )}
              {response.rejection_note && <Paragraph>补充说明：{response.rejection_note}</Paragraph>}
            </div>
          </div>
        ) : (
          <>
            <Divider />
            <div className="candidate-offer-actions">
              <Button size="large" danger onClick={() => openResponse('rejected')}>拒绝 Offer</Button>
              <Button size="large" type="primary" icon={<CheckCircleOutlined />} onClick={() => openResponse('accepted')}>接受 Offer</Button>
            </div>
          </>
        )}

        <Text type="secondary" className="candidate-offer-verification-expiry">
          身份验证有效至 {formatDateTime(verification.expiresAt)}
        </Text>
      </section>

      <Modal
        title={responseTarget?.decision === 'accepted' ? '确认接受 Offer' : '确认拒绝 Offer'}
        open={Boolean(responseTarget)}
        okText={responseTarget?.decision === 'accepted' ? '确认接受' : '确认拒绝'}
        cancelText="返回"
        okButtonProps={{ danger: responseTarget?.decision === 'rejected' }}
        confirmLoading={responseMutation.isPending}
        onOk={submitResponse}
        onCancel={() => {
          setResponseTarget(undefined)
          rejectionForm.resetFields()
          responseMutation.reset()
        }}
      >
        {responseMutation.error && (
          <Alert
            type="error"
            showIcon
            message={portalErrorContent(responseMutation.error).message}
          />
        )}
        {responseTarget?.decision === 'accepted' ? (
          <Paragraph>确认后回应不能修改。</Paragraph>
        ) : (
          <Form<RejectionValues> form={rejectionForm} layout="vertical">
            <Form.Item
              label="拒绝原因"
              name="reason"
              rules={[{ required: true, message: '请选择拒绝原因' }]}
            >
              <Select
                options={Object.entries(rejectionReasonLabels).map(([value, label]) => ({
                  value,
                  label,
                }))}
              />
            </Form.Item>
            <Form.Item label="补充说明" name="note">
              <Input.TextArea rows={4} maxLength={2_000} showCount />
            </Form.Item>
          </Form>
        )}
      </Modal>
    </PortalShell>
  )
}
